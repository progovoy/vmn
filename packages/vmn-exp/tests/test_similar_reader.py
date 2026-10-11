"""``vmn_exp.sdk.reader.similar_runs`` and ``run.similar()``: the past runs most
like a run, from Python — the same items ``vmn-exp similar --json`` prints."""
import os

import pytest
from exp_helpers import _bootstrap, _storage
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.core.query import QueryError
from vmn_exp.sdk import start_run
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.sdk.reader import similar_runs
from vmn_exp.snapshot import open_storage

APP = "trainer"
ITEM_KEYS = {"app", "verstr", "name", "score", "reasons", "signals", "group_size", "author",
             "timestamp", "status", "goal", "note", "intent", "features"}
CHANGES = features(["train.py"], [TRAIN_STEP])


@pytest.fixture
def storage(tmp_path):
    return open_storage(root=str(tmp_path / "store"), area="runs")


def _verstrs(items):
    return [item["verstr"] for item in items]


def test_similar_runs_returns_the_cli_json_items(storage):
    target = seed(storage, APP, verstr(1), changes=CHANGES, ts="2026-01-01T00:00:00Z")
    other = seed(storage, APP, verstr(2), changes=CHANGES, ts="2026-01-02T00:00:00Z",
                 metrics={"loss": 0.2}, goal=("loss", "min"), exit_code=0)

    [item] = similar_runs(APP, target, storage=storage)

    assert set(item) == ITEM_KEYS and item["verstr"] == other
    assert item["status"] == "succeeded" and item["goal"]["value"] == 0.2
    # The default ref is the latest run, which never matches itself.
    assert _verstrs(similar_runs(APP, storage=storage)) == [target]


def test_query_top_and_all_apps(storage):
    target = seed(storage, APP, verstr(1), changes=CHANGES)
    for n, lr in ((2, 0.1), (3, 0.001), (4, 0.5)):
        seed(storage, APP, verstr(n), changes=CHANGES, params={"lr": lr})
    elsewhere = seed(storage, "other_app", verstr(5), changes=CHANGES)

    assert sorted(_verstrs(similar_runs(APP, target, storage=storage, query="params.lr > 0.01"))) \
        == [verstr(2), verstr(4)]
    assert len(similar_runs(APP, target, storage=storage, top=1)) == 1
    found = similar_runs(APP, target, storage=storage, all_apps=True)
    assert ("other_app", elsewhere) in {(i["app"], i["verstr"]) for i in found}
    with pytest.raises(QueryError):
        similar_runs(APP, target, storage=storage, query="params.lr >")


def test_a_context_text_and_a_pure_text_query(storage):
    target = seed(storage, APP, verstr(1), intent={"text": "focal loss"})
    smoothing = seed(storage, APP, verstr(2), intent={"text": "label smoothing"})
    seed(storage, APP, verstr(3), intent={"text": "focal loss again"})

    assert _verstrs(similar_runs(APP, target, storage=storage, context="label smoothing"))[0] \
        == smoothing
    [item] = similar_runs(APP, None, storage=storage, context="label smoothing", text_only=True)
    assert item["verstr"] == smoothing and set(item["signals"]) == {"text"}
    with pytest.raises(ValueError):
        similar_runs(APP, None, storage=storage, text_only=True)


def test_an_unknown_ref_raises_value_error(storage):
    seed(storage, APP, verstr(1), changes=CHANGES)
    with pytest.raises(ValueError):
        similar_runs(APP, verstr(9), storage=storage)


def test_run_similar_finds_runs_like_the_open_run(app_layout, monkeypatch):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push(
        "test_repo_0", "train.py", "def train_step():\n    a = 1\n    b = 2\n    return a\n")
    prior = seed(_storage(app_layout), app_layout.app_name, verstr(1, commit="0000000"),
                 intent={"text": "label smoothing on the targets"})
    with open(os.path.join(app_layout.repo_path, "train.py"), "w") as f:
        f.write("def train_step():\n    a = 1\n    b = 2\n    return b\n")
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)

    with start_run(app_layout.app_name) as run:
        run.set_intent("label smoothing, again")
        found = run.similar(top=3)

    assert _verstrs(found) == [prior]


def test_a_no_op_run_has_no_similar_runs():
    assert NoOpRun("app").similar() == [] and NoOpRun("app").similar(top=3) == []
