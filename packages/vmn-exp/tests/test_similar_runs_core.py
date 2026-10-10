"""Similar runs over a snapshot (vmn_exp.core.similar): candidates, exclusions,
text-only and context queries, apps, filters and the result shape."""
import pytest
from similar_fixtures import FakeSnapshot, changed, dataset, run, verstrs
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.similar import similar_runs, similar_runs_multi, target_from_snapshot

LOSS = changed(files=["src/loss.py"], symbols=["src/loss.py::focal_loss"])


def _target(row, features=None, **kw):
    return dict({"row": row, "features": features, "intent": None, "hypothesis": None,
                 "text": None, "text_only": False}, **kw)


def test_the_closest_run_ranks_first_with_its_reasons_and_row():
    target = run("t", commit="ttttttt", params={"lr": 0.1})
    close = run("close", commit="ttttttt", params={"lr": 0.1})
    far = run("far", commit="fffffff", base="3.0.0", params={"lr": 0.5, "bs": 4})
    snapshot = FakeSnapshot([target, close, far], features={"t": LOSS, "close": LOSS})
    items = similar_runs(snapshot, _target(target, LOSS), app="app")
    assert verstrs(items) == ["close", "far"]
    best = items[0]
    assert set(best) >= {"app", "verstr", "score", "reasons", "signals", "group_size", "row"}
    assert best["app"] == "app" and best["group_size"] == 1
    assert best["score"] == 1.0
    assert best["reasons"][0] == "1 shared function: loss.py::focal_loss"
    assert best["row"] == close and best["row"] is not close
    assert 0 < items[1]["score"] < best["score"]


def test_the_target_its_code_and_its_sweep_are_left_out():
    params = {"lr": 0.1}
    rows = [
        run("outer", params=params),
        run("t", parent="outer", params=params),
        run("sibling", parent="outer", params=params),
        run("repeat", code=run("t")["code_verstr"], params=params),
        run("other", params=params),
    ]
    items = similar_runs(FakeSnapshot(rows), _target(rows[1]))
    assert verstrs(items) == ["other"]


def test_the_children_of_an_outer_target_are_left_out():
    rows = [run("outer", params={"a": 1}), run("child", parent="outer", params={"a": 1}),
            run("other", params={"a": 1})]
    assert verstrs(similar_runs(FakeSnapshot(rows), _target(rows[0]))) == ["other"]


def test_a_working_tree_target_without_a_verstr_excludes_nothing():
    rows = [run("a", params={"lr": 0.1})]
    working_tree = {"code_verstr": rows[0]["code_verstr"], "params": {"lr": 0.1}}
    assert verstrs(similar_runs(FakeSnapshot(rows), _target(working_tree))) == ["a"]


def test_a_target_without_any_signal_finds_nothing():
    rows = [run("a", params={"lr": 0.1})]
    assert similar_runs(FakeSnapshot(rows), _target(None)) == []


def test_top_limits_the_results():
    rows = [run(f"r{i}", params={"lr": 0.1}) for i in range(5)]
    assert len(similar_runs(FakeSnapshot(rows), _target(run("t", params={"lr": 0.1})), top=2)) == 2


def test_rows_filter_keeps_only_the_rows_it_accepts():
    rows = [run("a", params={"lr": 0.1}), run("b", params={"lr": 0.1})]
    items = similar_runs(FakeSnapshot(rows), _target(run("t", params={"lr": 0.1})),
                         rows_filter=lambda row: row["verstr"] != "a")
    assert verstrs(items) == ["b"]


def test_conf_weights_reorder_the_results():
    target = run("t", params={"lr": 0.1}, inputs=dataset("imagenet@3", "sha256:1"))
    same_code = run("code", params={"lr": 0.9})
    same_data = run("data", commit="bbbbbbb", base="4.0.0", params={"lr": 0.9},
                    inputs=dataset("imagenet@3", "sha256:1"))
    snapshot = FakeSnapshot([target, same_code, same_data])
    assert verstrs(similar_runs(snapshot, _target(target), weights={"inputs": 20})) == [
        "data", "code"]
    assert verstrs(similar_runs(snapshot, _target(target), weights={"code": 10})) == [
        "code", "data"]


def test_the_entrypoint_is_read_from_the_snapshot_run_states():
    rows = [run("a", commit="bbbbbbb", base="9.0.0")]
    snapshot = FakeSnapshot(rows, run_states={"a": {"command": ["python", "train.py"]}})
    target = _target(run("t"), command=["python", "train.py"])
    [item] = similar_runs(snapshot, target)
    assert item["signals"]["entrypoint"] == 1.0


def test_text_only_ranks_by_text_and_ignores_structure():
    target = run("t", params={"lr": 0.1}, note="label smoothing")
    rows = [target, run("struct", params={"lr": 0.1}),
            run("text", commit="zzzzzzz", note="tried label smoothing once")]
    items = similar_runs(FakeSnapshot(rows), _target(target, text_only=True))
    assert verstrs(items) == ["text"]
    assert items[0]["signals"] == {"text": 1.0}
    assert items[0]["reasons"] == ["shared: label, smoothing"]


def test_a_context_text_replaces_the_target_document():
    target = run("t", note="focal loss")
    rows = [target, run("focal", note="focal loss"), run("smooth", note="label smoothing")]
    items = similar_runs(FakeSnapshot(rows), _target(target, text="label smoothing", text_only=True))
    assert verstrs(items) == ["smooth"]


def test_a_text_question_without_a_run_finds_runs_by_their_intent():
    rows = [run("a", note="baseline"), run("b")]
    snapshot = FakeSnapshot(rows, intents={"b": {"text": "Try label smoothing", "keywords": []}})
    items = similar_runs(snapshot, _target(None, text="has anyone tried label smoothing?",
                                           text_only=True))
    assert verstrs(items) == ["b"]


def test_intent_keywords_outrank_a_passing_mention():
    rows = [run("mention", note="smoothing"), run("keyword"), run("other", note="adam")]
    snapshot = FakeSnapshot(rows, intents={"keyword": {"text": "", "keywords": ["smoothing"]}})
    items = similar_runs(snapshot, _target(None, text="smoothing", text_only=True))
    assert verstrs(items) == ["keyword", "mention"]
    assert items[0]["score"] == 1.0 > items[1]["score"]


def test_text_scores_are_normalised_by_the_best_candidate():
    rows = [run("a", note="focal loss gamma"), run("b", note="focal")]
    items = similar_runs(FakeSnapshot(rows), _target(None, text="focal loss gamma", text_only=True))
    assert items[0]["score"] == 1.0
    assert 0 < items[1]["score"] < 1.0


def test_the_hypothesis_and_commit_subjects_feed_the_text():
    rows = [run("a"), run("b")]
    snapshot = FakeSnapshot(rows, features={"a": {"commits": ["wire focal loss"]}},
                            hypotheses={"b": "gamma two helps recall"})
    assert verstrs(similar_runs(snapshot, _target(None, text="focal", text_only=True))) == ["a"]
    assert verstrs(similar_runs(snapshot, _target(None, text="recall", text_only=True))) == ["b"]


def test_runs_of_several_apps_merge_by_score_and_carry_their_app():
    target = run("t", params={"lr": 0.1})
    near = FakeSnapshot([target, run("n", params={"lr": 0.1})])
    far = FakeSnapshot([run("f", commit="bbbbbbb", params={"lr": 0.1, "bs": 2})])
    items = similar_runs_multi([("one", near, None), ("two", far, None)],
                               dict(_target(target), app="one"))
    assert [(i["app"], i["verstr"]) for i in items] == [("one", "n"), ("two", "f")]
    assert items[0]["score"] > items[1]["score"]


def test_exclusions_apply_to_the_target_app_only():
    target = run("t", params={"lr": 0.1})
    twin = FakeSnapshot([run("t", params={"lr": 0.1})])
    items = similar_runs_multi([("one", FakeSnapshot([target]), None), ("two", twin, None)],
                               dict(_target(target), app="one"))
    assert [(i["app"], i["verstr"]) for i in items] == [("two", "t")]


def test_target_from_snapshot_reads_the_runs_side_tables():
    rows = [run("t", note="n")]
    snapshot = FakeSnapshot(rows, features={"t": LOSS}, intents={"t": {"text": "x"}},
                            hypotheses={"t": "h"}, run_states={"t": {"command": ["a.py"]}})
    target = target_from_snapshot(snapshot, "t", text="ctx", text_only=True)
    assert target["row"] is rows[0]
    assert (target["features"], target["intent"], target["hypothesis"]) == (LOSS, {"text": "x"}, "h")
    assert (target["text"], target["text_only"], target["command"]) == ("ctx", True, ["a.py"])
    with pytest.raises(KeyError):
        target_from_snapshot(snapshot, "missing")


def test_a_real_index_snapshot_serves_as_the_snapshot():
    rows = [run("t", params={"lr": 0.1}), run("a", params={"lr": 0.1}, metrics={"acc": 1.0})]
    snapshot = IndexSnapshot.build("app", 1, rows, {"a": {"command": ["python", "x.py"]}},
                                   declared_defs={"a": {"acc": {"goal": "max"}}})
    [item] = similar_runs(snapshot, target_from_snapshot(snapshot, "t"), app="app")
    assert item["verstr"] == "a"
    assert item["goal"] == {"metric": "acc", "goal": "max", "value": 1.0}


def test_a_create_note_is_part_of_the_target_text_too():
    rows = [run("t"), run("a", commit="bbbbbbb", base="9.0.0", note="focal loss")]
    snapshot = FakeSnapshot(rows, create_notes={"t": "focal loss try"})
    target = target_from_snapshot(snapshot, "t", text_only=True)
    assert verstrs(similar_runs(snapshot, target)) == ["a"]
