"""A restarted ``vmn-exp ui`` whose newest runs are all trials still shows
its outer runs while it reads its persisted index back: the first rows hold
the trials' ancestors and the newest outer runs, so the facets count jobs
(the Outer runs view's kind) and ``top=jobs`` lists them."""
import gc
import threading
import time

import pytest

pytest.importorskip("fastapi")
moto = pytest.importorskip("moto")
import boto3  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import vmn_exp.core.index as index_module  # noqa: E402
from vmn_exp.core.index_store import SqliteStore  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "app"
FIRST, TRIALS = 5, 8
N = 3 * 2 + 2 * 2 + TRIALS  # three drivers and launches, two old trials each but the newest
API = f"/api/v1/workspaces/ws/apps/{APP}"


def _save(storage, verstr, second, parent=None):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z"}
    storage.save(APP, verstr, dict(meta, parent=parent) if parent else meta, {})


def _runs(storage):
    """Drivers ``d0``..``d2``, each → a launch → trials; the newest FIRST
    runs are all trials of ``d2``."""
    for n, (start, trials) in enumerate([(0, 2), (10, 2), (30, TRIALS)]):
        _save(storage, f"d{n}", start)
        _save(storage, f"l{n}", start + 1, f"d{n}")
        for k in range(trials):
            _save(storage, f"t{n}.{k}", start + 2 + k, f"l{n}")


@pytest.fixture
def restart(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(index_module, "FIRST_ROWS", FIRST)
    apps = []
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        _runs(S3SnapshotStorage("vmn-bucket", prefix="st/runs"))
        from vmn_exp.ui.server import create_app
        from vmn_exp.ui.workspaces import WorkspaceManager

        WorkspaceManager(str(tmp_path / "data")).add_store("ws", "s3://vmn-bucket/st")

        def start():
            for app in apps:
                app.state.refresher.stop()
            monkeypatch.setattr(index_module, "_SHARED", {})
            gc.collect()
            apps.append(create_app(WorkspaceManager(str(tmp_path / "data")),
                                   background_refresh=True))
            return TestClient(apps[-1])

        yield start
        for app in apps:
            app.state.refresher.stop()


def _indexed(client, timeout=30):
    deadline = time.monotonic() + timeout
    status = client.get(f"{API}/experiments-status").json()
    while (status.get("total") != N or "indexing" in status) and time.monotonic() < deadline:
        time.sleep(0.05)
        status = client.get(f"{API}/experiments-status").json()
    return status


def test_a_restarted_server_lists_its_outer_runs_while_it_reads_its_index_back(
        restart, monkeypatch):
    assert _indexed(restart())["total"] == N
    release, real = threading.Event(), SqliteStore.load_warm
    monkeypatch.setattr(SqliteStore, "load_warm",
                        lambda self, app_name: release.wait(10) and real(self, app_name))
    try:
        client = restart()
        status = client.get(f"{API}/experiments-status").json()
        facets = client.get(f"{API}/experiments-facets").json()
        jobs = client.get(f"{API}/experiments?limit=50&top=jobs").json()
    finally:
        release.set()

    assert status["indexing"]["total"] == N
    assert facets["jobs"] == 3
    assert {row["verstr"] for row in jobs["rows"]} == {"d0", "d1", "d2"}
