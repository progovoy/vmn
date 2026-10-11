"""The search ``vmn-exp similar``, the submission hint and the SDK reader share
(:mod:`vmn_exp.core.similar_search`): each result as one JSON item saying who
ran it, when, how it ended and did, what it was for and what it changed —
candidates narrowed by ``--query`` and without archived runs — plus the
conf's ``experiment.similar`` section."""
import pytest
from similar_fixtures import FakeSnapshot, changed, run, verstrs
from vmn_exp.core import similar_search
from vmn_exp.core.query import QueryError
from vmn_exp.core.similar_search import (
    INTENT_EXCERPT_BYTES,
    conf_weights,
    hint_enabled,
    intent_excerpt,
    search,
    similar_conf,
    text_target,
)

SYMS = ["train.py::train_step"]
TARGET = {"row": None, "features": changed(["train.py"], SYMS)}
ITEM_KEYS = {"app", "verstr", "name", "score", "reasons", "signals", "group_size", "author",
             "timestamp", "status", "goal", "note", "intent", "features"}


def _snapshot(*rows, **tables):
    tables.setdefault("features", {r["verstr"]: changed(["train.py"], SYMS) for r in rows})
    return FakeSnapshot(rows, **tables)


def test_an_item_says_who_when_how_and_what_of_the_run():
    row = run("a", name="focal", author="alice@x.io", timestamp="2026-02-01T00:00:00Z",
              metrics={"val_loss": 0.3})
    intent = {"text": "focal loss", "keywords": ["imbalance"], "generator": "m", "source": "user"}
    snap = _snapshot(row, intents={"a": intent}, declared={"val_loss": {"goal": "min"}},
                     run_states={"a": {"exit_code": 0}}, create_notes={"a": "first try"})

    [item] = search(None, "app", snap, TARGET)

    assert set(item) == ITEM_KEYS
    assert (item["app"], item["verstr"], item["name"]) == ("app", "a", "focal")
    assert (item["author"], item["timestamp"]) == ("alice@x.io", "2026-02-01T00:00:00Z")
    assert item["status"] == "succeeded"
    assert item["goal"] == {"metric": "val_loss", "goal": "min", "value": 0.3}
    assert item["note"] == "first try"  # the create note, when the record has none
    assert item["intent"] == {"text": "focal loss", "keywords": ["imbalance"], "generator": "m"}
    assert item["features"]["changed"]["symbols"] == SYMS
    assert item["group_size"] == 1 and item["score"] > 0 and item["reasons"]


def test_the_record_note_wins_over_the_create_note_and_a_run_without_state_is_created():
    snap = _snapshot(run("a", note="kept"), create_notes={"a": "first try"})
    [item] = search(None, "app", snap, TARGET)
    assert (item["note"], item["status"]) == ("kept", "created")


def test_an_item_copies_the_features_it_returns():
    snap = _snapshot(run("a"))
    [item] = search(None, "app", snap, TARGET)
    item["features"]["changed"]["symbols"].append("x.py::y")
    assert snap.features_of("a")["changed"]["symbols"] == SYMS


def test_an_intent_excerpt_is_the_first_2048_bytes_on_a_character_boundary():
    excerpt = intent_excerpt({"text": "é" * 2000, "keywords": ["k"], "source": "user"})
    raw = excerpt["text"].encode("utf-8")
    assert len(raw) <= INTENT_EXCERPT_BYTES and len(raw) >= INTENT_EXCERPT_BYTES - 1
    assert excerpt["truncated"] is True and excerpt["keywords"] == ["k"]
    assert "generator" not in excerpt and "source" not in excerpt
    assert intent_excerpt({"text": "short", "truncated": True})["truncated"] is True
    assert "truncated" not in intent_excerpt({"text": "short"})
    assert intent_excerpt(None) is None


def test_a_query_narrows_the_candidates_on_annotated_rows():
    snap = _snapshot(run("a", params={"lr": 0.1}), run("b", params={"lr": 0.001}),
                     run_states={"a": {"exit_code": 0}, "b": {"exit_code": 1}})
    assert sorted(verstrs(search(None, "app", snap, TARGET))) == ["a", "b"]
    assert verstrs(search(None, "app", snap, TARGET, query="params.lr > 0.01")) == ["a"]
    assert verstrs(search(None, "app", snap, TARGET, query='status = "failed"')) == ["b"]


def test_a_bad_query_raises_query_error():
    with pytest.raises(QueryError):
        search(None, "app", _snapshot(run("a")), TARGET, query="metrics.loss <")


def test_archived_runs_are_left_out_unless_asked_for():
    snap = _snapshot(run("a"), run("b", archived=True))
    assert verstrs(search(None, "app", snap, TARGET)) == ["a"]
    assert sorted(verstrs(search(None, "app", snap, TARGET, include_archived=True))) == ["a", "b"]


def test_top_caps_the_items():
    snap = _snapshot(*(run(f"r{i}") for i in range(5)))
    assert len(search(None, "app", snap, TARGET, top=2)) == 2


def test_a_text_target_is_a_pure_text_query():
    snap = _snapshot(run("a"), run("b"), features={},
                     intents={"a": {"text": "label smoothing helps"},
                              "b": {"text": "focal loss for imbalance"}})
    [item] = search(None, "app", snap, text_target("label smoothing"))
    assert item["verstr"] == "a" and set(item["signals"]) == {"text"}


def test_the_conf_similar_section_tolerates_any_shape():
    assert similar_conf(None) == {} and similar_conf({"similar": "x"}) == {}
    assert similar_conf("bogus") == {}
    assert hint_enabled({}) and hint_enabled({"similar": {"hint": "no"}})
    assert not hint_enabled({"similar": {"hint": False}})
    assert conf_weights({"similar": {"weights": {"text": 3}}}) == {"text": 3}
    assert conf_weights({}) is None


def test_invalid_weights_never_break_a_search():
    snap = _snapshot(run("a"))
    for weights in ("bogus", {"symbols": "lots", "nope": 1, "files": -2}, [1, 2]):
        assert verstrs(search(None, "app", snap, TARGET, weights=weights)) == ["a"]


def test_conf_schema_is_the_metrics_mapping_or_empty():
    assert similar_search.conf_schema({"metrics": {"loss": {"goal": "min"}}}) == {
        "loss": {"goal": "min"}}
    assert similar_search.conf_schema({"metrics": "x"}) == {}
    assert similar_search.conf_schema("x") == {}
