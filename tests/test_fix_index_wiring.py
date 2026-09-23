"""The experiment index behind every leaderboard reader: the ui index, S3
workspaces, the SDK's list_runs and ``vmn exp list``."""
import collections
import os
import subprocess

import pytest
from helpers import _bootstrap, _exp, _storage

from version_stamp.cli.snapshot import LocalSnapshotStorage

pytest.importorskip("fastapi")


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _append(app_layout, verstr, ts, **values):
    _storage(app_layout).append_log_entry(
        app_layout.app_name, verstr, "w9",
        {"timestamp": ts, "type": "metrics", "values": values},
    )


@pytest.fixture
def log_reads(monkeypatch):
    """Whole-log reads through the storage (the pre-index read path)."""
    calls = []
    real = LocalSnapshotStorage.load_logs_by_writer

    def spy(self, app_name, verstr):
        calls.append(verstr)
        return real(self, app_name, verstr)

    monkeypatch.setattr(LocalSnapshotStorage, "load_logs_by_writer", spy)
    return calls


# ---------------------------------------------------------------------------
# SDK list_runs
# ---------------------------------------------------------------------------


def test_list_runs_persists_an_ignored_index_and_rereads_nothing(app_layout, log_reads):
    from version_stamp.exp.reader import list_runs

    _bootstrap(app_layout)
    first = _create(app_layout, "--metrics", "loss=0.4")
    _create(app_layout, "--metrics", "loss=0.2")

    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))
    assert [r["metrics"]["loss"] for r in rows] == [0.4, 0.2]

    base = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "experiments")
    assert os.path.isfile(os.path.join(base, ".index.sqlite"))
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=app_layout.repo_path, capture_output=True, text=True,
    ).stdout
    assert ".index.sqlite" not in status

    log_reads.clear()
    _append(app_layout, first, "2099-01-01T00:00:00Z", loss=0.01)
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))
    assert rows[0]["metrics"]["loss"] == 0.01
    assert log_reads == []  # the grown log was read from its old end, not reloaded


def test_list_runs_falls_back_when_the_index_cannot_be_opened(app_layout, monkeypatch):
    from version_stamp.core import experiment_index
    from version_stamp.exp.reader import list_runs

    _bootstrap(app_layout)
    _create(app_layout, "--metrics", "loss=0.4")

    def broken(*a, **kw):
        raise RuntimeError("no index today")

    monkeypatch.setattr(experiment_index, "shared_index", broken)
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))
    assert [r["metrics"]["loss"] for r in rows] == [0.4]


# ---------------------------------------------------------------------------
# vmn exp list
# ---------------------------------------------------------------------------


def test_exp_list_serves_appended_metrics_from_the_index(app_layout, capfd, log_reads):
    _bootstrap(app_layout)
    first = _create(app_layout, "--metrics", "loss=0.4", "--note", "baseline")
    _create(app_layout, "--metrics", "loss=0.2")

    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert "loss=0.4" in out and "baseline" in out

    log_reads.clear()
    _append(app_layout, first, "2099-01-01T00:00:00Z", loss=0.05)
    assert _exp(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert "loss=0.05" in out
    assert log_reads == []


# ---------------------------------------------------------------------------
# vmn ui: git workspaces (WorkspaceIndex) and S3 workspaces
# ---------------------------------------------------------------------------


def test_workspace_index_folds_an_append_without_reloading_logs(app_layout, log_reads, tmp_path):
    from version_stamp.ui.index import WorkspaceIndex

    _bootstrap(app_layout)
    first = _create(app_layout, "--metrics", "loss=0.4")
    index = WorkspaceIndex(app_layout.repo_path, db_dir=str(tmp_path / "idx"))
    assert index.list_experiments(app_layout.app_name)[0]["metrics"]["loss"] == 0.4

    log_reads.clear()
    _append(app_layout, first, "2099-01-01T00:00:00Z", loss=0.03)
    assert index.list_experiments(app_layout.app_name)[0]["metrics"]["loss"] == 0.03
    assert log_reads == []

    # A new server process over the same data dir starts warm.
    restarted = WorkspaceIndex(app_layout.repo_path, db_dir=str(tmp_path / "idx"))
    assert restarted.list_experiments(app_layout.app_name)[0]["metrics"]["loss"] == 0.03
    assert log_reads == []


def test_s3_workspace_listing_is_cached_across_requests(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    from version_stamp.cli.snapshot import S3SnapshotStorage
    from version_stamp.ui.readers.experiments import list_experiments_from_storage

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket="vmn-bucket")
        seed = S3SnapshotStorage("vmn-bucket", prefix="cached-exps")
        for i in range(5):
            v = f"0.0.1-dev.abc.r{i}"
            seed.save("app", v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
            seed.append_log_entry("app", v, "w", {
                "timestamp": "t", "type": "metrics", "values": {"loss": i},
            })

        def request():
            # The server builds a fresh storage object for every request.
            storage = S3SnapshotStorage("vmn-bucket", prefix="cached-exps")
            calls = collections.Counter()
            storage._s3.meta.events.register(
                "before-call.s3", lambda event_name, **kw: calls.update([event_name])
            )
            rows = list_experiments_from_storage(storage, "app")
            return rows, calls

        cold, _ = request()
        warm, calls = request()
        assert warm == cold and len(warm) == 5
        assert not any("GetObject" in name for name in calls)
