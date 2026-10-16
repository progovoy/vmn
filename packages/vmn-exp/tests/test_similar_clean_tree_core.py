"""A run whose features entry names no changes ran a clean tree: its changes
are known to be none, so it files a clean token in ``files`` and ``symbols``
— against a run that changed code their overlap is 0, and two clean trees
are alike in both. Unknown stays unknown — no features entry, an MLflow
import's, an export's author-only entry or a backfill that found the code
gone — and those signals are left out (vmn_exp.core.similar_doc)."""
import pytest
from similar_fixtures import FakeSnapshot, changed, explain, run
from vmn_exp.core.similar import similar_runs, target_from_snapshot

CMD = ["python", "train.py", "--lr", "0.1"]
FOCAL = changed(files=["src/loss.py"], symbols=["src/loss.py::focal_loss"])
# A clean tree's capture: build_features_entry drops the empty ``changed``.
CLEAN = {"features_version": 1, "source": "capture",
         "author": {"git_user_email": "bob@x.io", "source": "git"}}


def _view(verstr, features, code=None, **fields):
    return {"row": run(verstr, code=code, **fields), "features": features}


def test_a_clean_capture_against_changed_code_shares_no_files_or_symbols():
    reasons, signals = explain(_view("t", FOCAL), _view("c", CLEAN))
    assert (signals["files"], signals["symbols"]) == (0.0, 0.0)
    assert reasons == ["same base commit aaaaaaa"]


def test_two_clean_trees_are_alike_in_files_and_symbols():
    reasons, signals = explain(_view("a", CLEAN), _view("b", CLEAN))
    assert (signals["files"], signals["symbols"]) == (1.0, 1.0)
    assert "both clean trees" in reasons


@pytest.mark.parametrize("clean", [CLEAN, {}, {"changed": {}}, changed(),
                                   dict(CLEAN, source="rerun"), dict(CLEAN, source="export")],
                         ids=["capture", "empty", "empty-changed", "empty-lists", "rerun",
                              "export"])
def test_any_entry_naming_no_changes_is_a_clean_tree(clean):
    signals = explain(_view("t", FOCAL), _view("c", clean))[1]
    assert (signals["files"], signals["symbols"]) == (0.0, 0.0)


@pytest.mark.parametrize("unknown", [
    None,
    {"features_version": 1, "source": "mlflow", "entrypoint": "train.py"},
    {"features_version": 0, "source": "export", "author": {"writer": "gpu-7"}},
    {"features_version": 1, "source": "backfill", "author": {"writer": "gpu-7"}},
], ids=["no-entry", "mlflow", "author-only-export", "partial-backfill"])
def test_changes_unknown_are_left_out_on_either_side(unknown):
    for a, b in ((_view("t", FOCAL), _view("u", unknown)), (_view("u", unknown), _view("t", FOCAL)),
                 (_view("c", CLEAN), _view("u", unknown))):
        signals = explain(a, b)[1]
        assert "files" not in signals and "symbols" not in signals


def test_a_backfill_naming_no_changes_is_clean_on_a_clean_code_verstr():
    backfilled = {"features_version": 1, "source": "backfill"}
    clean_code = "1.0.0-dev.aaaaaaa.0000000"
    signals = explain(_view("t", FOCAL), _view("c", backfilled, code=clean_code))[1]
    assert (signals["files"], signals["symbols"]) == (0.0, 0.0)


def test_a_clean_tree_against_changes_naming_no_function_leaves_symbols_out():
    readme = changed(files=["README.md"])
    signals = explain(_view("t", readme), _view("c", CLEAN))[1]
    assert signals["files"] == 0.0 and "symbols" not in signals


def test_the_same_changed_function_outranks_a_clean_twin_on_common_code():
    # Ranking is bm25: what most runs share (the commit, params, command) weighs
    # little, a function few runs changed weighs much (plan 24).
    twin_fields = dict(commit="ttttttt", base="1.2.0", params={"lr": 0.1, "bs": 32},
                       command=CMD, metrics={"val_loss": 0.35}, branch="feat/focal")
    target = run("t", **twin_fields)
    same_fn = run("same_fn", commit="ooooooo", base="1.1.0", params={"lr": 0.3, "bs": 64},
                  command=CMD, metrics={"val_loss": 0.4}, branch="feat/old")
    clean = run("clean", code="1.2.0-dev.ttttttt.0000000", **twin_fields)
    others = [run(f"o{i}", **twin_fields) for i in range(20)]
    features = {"t": FOCAL, "clean": CLEAN,
                "same_fn": changed(files=["src/loss.py", "README.md"],
                                   symbols=["src/loss.py::focal_loss"])}
    features.update((o["verstr"], changed(files=[f"src/d{i}.py"], symbols=[f"src/d{i}.py::f"]))
                    for i, o in enumerate(others))
    snap = FakeSnapshot([target, same_fn, clean, *others], features=features)

    items = {i["verstr"]: i for i in similar_runs(snap, target_from_snapshot(snap, "t"), top=30)}

    assert max(items, key=lambda v: items[v]["score"]) == "same_fn"
    assert items["clean"]["score"] < 1.0
    assert (items["clean"]["signals"]["files"], items["clean"]["signals"]["symbols"]) == (0, 0)
