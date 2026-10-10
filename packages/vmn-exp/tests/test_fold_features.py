"""Folding the facts a run's log states about it: ``features``, ``intent``
and the create entry's ``hypothesis``.

The ``features`` entry with the highest ``features_version`` wins, the latest
of those first; the latest ``intent`` wins; the hypothesis is the first
``create`` entry's, like its note. None of them is pre-created by
``new_fold``, malformed entries fold into nothing, and rows gain only the
small ``author`` and ``has_intent`` fields.
"""
import pytest
from vmn_exp.core.fold import (
    apply_entries,
    author_display,
    fold_features,
    fold_hypothesis,
    fold_intent,
    fold_log,
    fold_row,
    new_fold,
)
from vmn_exp.core.log import experiment_row

META = {"verstr": "0.0.1-dev.a", "timestamp": "2026-01-01T00:00:00Z"}
AUTHOR = {"writer": "gpu-07", "git_user_email": "a@x.io", "os_user": "alice", "source": "git"}


def _features(ts, version=1, author=AUTHOR, files=("src/loss.py",)):
    return {"timestamp": ts, "type": "features", "features_version": version,
            "source": "capture", "author": dict(author),
            "changed": {"files": list(files), "symbols": ["src/loss.py::focal_loss"]},
            "commits": ["try focal loss"]}


def _intent(ts, text="focal loss for the long tail"):
    return {"timestamp": ts, "type": "intent", "text": text, "keywords": ["focal loss"],
            "source": "user"}


def _create(ts, hypothesis=None, note=None):
    entry = {"timestamp": ts, "type": "create", "params": {}, "note": note}
    if hypothesis is not None:
        entry["hypothesis"] = hypothesis
    return entry


def test_a_fresh_fold_holds_none_of_them():
    fold = new_fold()
    assert not {"features", "intent", "hypothesis"} & set(fold)
    assert (fold_features(fold), fold_intent(fold), fold_hypothesis(fold)) == (None, None, None)


def test_features_value_is_the_entry_without_type_and_timestamp():
    fold = fold_log([_features("t1")])
    assert fold_features(fold) == {
        "features_version": 1, "source": "capture", "author": AUTHOR,
        "changed": {"files": ["src/loss.py"], "symbols": ["src/loss.py::focal_loss"]},
        "commits": ["try focal loss"],
    }


def test_the_latest_features_entry_of_one_version_wins():
    fold = fold_log([_features("t1", files=["old.py"]), _features("t2", files=["new.py"])])
    assert fold_features(fold)["changed"]["files"] == ["new.py"]


def test_a_higher_features_version_beats_a_later_lower_one():
    log = [_features("t1", version=2, files=["v2.py"]), _features("t2", version=1, files=["v1.py"])]
    assert fold_features(fold_log(log))["changed"]["files"] == ["v2.py"]
    fold = apply_entries(new_fold(), "w2", 0, [log[1]])
    apply_entries(fold, "w1", 0, [log[0]])
    assert fold_features(fold)["features_version"] == 2


def test_an_older_features_entry_arriving_later_does_not_win():
    fold = apply_entries(new_fold(), "w2", 0, [_features("t2", files=["new.py"])])
    apply_entries(fold, "w1", 0, [_features("t1", files=["old.py"])])
    assert fold_features(fold)["changed"]["files"] == ["new.py"]


@pytest.mark.parametrize("version", [None, "1", True, 1.0])
def test_a_features_entry_without_an_int_version_is_ignored(version):
    entry = _features("t2")
    entry["features_version"] = version
    if version is None:
        del entry["features_version"]
    assert fold_features(fold_log([entry])) is None
    assert fold_features(fold_log([_features("t1", files=["ok.py"]), entry]))["changed"] == {
        "files": ["ok.py"], "symbols": ["src/loss.py::focal_loss"]}


def test_the_latest_intent_wins_across_writers():
    fold = apply_entries(new_fold(), "w2", 0, [_intent("t2", "newer")])
    apply_entries(fold, "w1", 0, [_intent("t1", "older")])
    assert fold_intent(fold) == {"text": "newer", "keywords": ["focal loss"], "source": "user"}
    assert fold_intent(fold_log([_intent("t1", "a"), _intent("t2", "b")]))["text"] == "b"


@pytest.mark.parametrize("text", [None, 3, ["x"]])
def test_an_intent_without_text_is_ignored(text):
    entry = _intent("t2")
    entry["text"] = text
    assert fold_intent(fold_log([_intent("t1", "kept"), entry]))["text"] == "kept"


def test_an_empty_intent_text_clears_the_intent():
    fold = fold_log([_intent("t1", "something"), _intent("t2", "  ")])
    assert fold_intent(fold) is None
    assert fold_row(1, META, fold)["has_intent"] is False


def test_the_hypothesis_is_the_first_create_entrys():
    fold = apply_entries(new_fold(), "w", 0, [_create("t2", "later")])
    apply_entries(fold, "a", 0, [_create("t1", "earliest")])
    assert fold_hypothesis(fold) == "earliest"
    assert fold_hypothesis(fold_log([_create("t1", "first"), _create("t2", "second")])) == "first"


def test_a_first_create_without_a_hypothesis_leaves_none():
    fold = apply_entries(new_fold(), "w", 0, [_create("t2", "later")])
    apply_entries(fold, "a", 0, [_create("t1")])
    assert fold_hypothesis(fold) is None
    assert "hypothesis" not in fold


@pytest.mark.parametrize("hypothesis", ["", "   ", 0.5, ["a"], {"k": "v"}])
def test_a_non_text_hypothesis_is_none(hypothesis):
    assert fold_hypothesis(fold_log([_create("t1", hypothesis)])) is None


@pytest.mark.parametrize("author, shown", [
    ({"writer": "w", "git_user_email": "a@x.io", "os_user": "alice"}, "a@x.io"),
    ({"writer": "w", "git_user_email": "", "os_user": "alice"}, "alice"),
    ({"writer": "w", "os_user": ""}, "w"),
    ({"writer": ""}, None),
    ({}, None),
    (None, None),
    ("a@x.io", None),
    ({"git_user_email": 7, "os_user": "alice"}, "alice"),
])
def test_author_display_takes_email_then_os_user_then_writer(author, shown):
    assert author_display(author) == shown


def test_rows_carry_author_and_has_intent_and_no_features():
    log = [_create("t0", "h"), _features("t1"), _intent("t2")]
    row = experiment_row(1, META, log)
    assert row["author"] == "a@x.io"
    assert row["has_intent"] is True
    assert not {"features", "intent", "hypothesis"} & set(row)


def test_a_row_without_facts_has_no_author_and_a_false_has_intent():
    row = fold_row(1, META, new_fold())
    assert row["author"] is None
    assert row["has_intent"] is False
    assert experiment_row(1, META, [{"timestamp": "t", "type": "note", "text": "hi"}])[
        "has_intent"] is False


def test_the_row_author_follows_the_winning_features_entry():
    log = [_features("t1", version=2, author={"os_user": "bob"}),
           _features("t2", version=1, author={"git_user_email": "c@x.io"})]
    assert experiment_row(1, META, log)["author"] == "bob"
