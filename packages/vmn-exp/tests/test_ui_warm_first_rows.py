"""A restarted ``vmn-exp ui`` on a remote store shows the newest persisted
runs while it reads the rest of its persisted index back: experiments-status
says ``indexing`` their share of every persisted run (not ``0`` of an
unknown total) and the board lists them."""
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
N, FIRST = 12, 5
STATUS = f"/api/v1/workspaces/ws/apps/{APP}/experiments-status"
BOARD = f"/api/v1/workspaces/ws/apps/{APP}/experiments?limit=50"


@pytest.fixture
def restart(tmp_path, monkeypatch):
    """``restart()`` -> a client of a server started over the store and
    index the previous server (stopped) left."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(index_module, "FIRST_ROWS", FIRST)
    apps = []
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        storage = S3SnapshotStorage("vmn-bucket", prefix="st/runs")
        for i in range(N):
            v = f"0.0.{i}"
            storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
        from vmn_exp.ui.server import create_app
        from vmn_exp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_store("ws", "s3://vmn-bucket/st")

        def start():
            for app in apps:  # the previous life: gone, its connections closed
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
    """*client*'s status once its index holds every run."""
    deadline = time.monotonic() + timeout
    status = client.get(STATUS).json()
    while (status.get("total") != N or "indexing" in status) and time.monotonic() < deadline:
        time.sleep(0.05)
        status = client.get(STATUS).json()
    return status


def test_a_restarted_server_shows_the_newest_runs_while_it_reads_its_index_back(
        restart, monkeypatch):
    assert _indexed(restart())["total"] == N
    release, real = threading.Event(), SqliteStore.load_warm
    monkeypatch.setattr(SqliteStore, "load_warm",
                        lambda self, app_name: release.wait(10) and real(self, app_name))
    try:
        client = restart()
        status = client.get(STATUS).json()
        board = client.get(BOARD).json()
    finally:
        release.set()

    assert status["indexing"] == {"loaded": FIRST, "total": N}
    assert {row["verstr"] for row in board["rows"]} == {f"0.0.{i}" for i in range(N - FIRST, N)}
