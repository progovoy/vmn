"""``import-mlflow --refresh-features --repo``: an already-imported run whose
features name its changes already is skipped without asking the checkout for
its source commit's changes; one without them still gets them."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.importers.import_records import import_run
from vmn_exp.importers.mlflow_filestore import iter_runs
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_ID = "d" * 32
COMMIT = "f" * 40
CHANGES = {"changed": {"files": ["train.py"]}, "changed_source": "commit"}


def _run(tmp_path):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", RUN_ID, tags={"mlflow.source.git.commit": COMMIT})
    return next(iter_runs(mlruns))


def test_a_refresh_asks_for_commit_changes_only_while_features_lack_them(
        tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "refresher")
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    run = _run(tmp_path)
    asked = []

    def changes(commit):
        asked.append(commit)
        return CHANGES

    assert import_run(storage, APP, run) == "created"
    assert import_run(storage, APP, run, refresh_features=True,
                      commit_changes=changes) == "refreshed"
    assert asked
    asked.clear()

    assert import_run(storage, APP, run, refresh_features=True,
                      commit_changes=changes) == "skipped"
    assert asked == []
