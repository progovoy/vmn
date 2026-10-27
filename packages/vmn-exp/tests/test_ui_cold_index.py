"""A store's ui answers at once while its cold index still lists the store:
experiments-status says it is indexing (the total unknown until the runs
are named) and the board answers empty — no request waits for the first
publish (at 497k S3 runs that took over an hour)."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
moto = pytest.importorskip("moto")
import boto3  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


@pytest.fixture
def held(tmp_path, monkeypatch):
    """A ui over a store of 3 runs whose record names are held back."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    release = threading.Event()
    real = S3SnapshotStorage.record_name_pages

    def held_pages(self, app_name):
        release.wait(20)
        yield from real(self, app_name)

    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        storage = S3SnapshotStorage("vmn-bucket", prefix="st/runs")
        for i in range(3):
            v = f"0.0.{i}"
            storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        monkeypatch.setattr(S3SnapshotStorage, "record_name_pages", held_pages)
        from vmn_exp.ui.server import create_app
        from vmn_exp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_store("ws", "s3://vmn-bucket/st")
        app = create_app(manager, background_refresh=True)
        yield TestClient(app), release
        release.set()
        app.state.refresher.stop()


def _timed(client, path, **params):
    started = time.monotonic()
    body = client.get(path, params=params).json()
    return time.monotonic() - started, body


def test_a_cold_index_answers_at_once_while_its_store_is_listed(held):
    client, release = held
    status_sec, status = _timed(client, f"{BASE}/experiments-status")
    board_sec, board = _timed(client, f"{BASE}/experiments", offset=0, limit=50)

    assert status_sec < 1.0 and board_sec < 1.0
    assert status["indexing"] == {"loaded": 0, "total": None}
    assert status["freshness"]["phase"] in ("full_listing", "loading_new")
    assert not status["freshness"]["refresh_failing"]
    assert board["total"] == 0
    release.set()
    deadline, done = time.monotonic() + 15, status
    while "indexing" in done and time.monotonic() < deadline:
        time.sleep(0.1)
        done = client.get(f"{BASE}/experiments-status").json()
    assert "indexing" not in done and done["total"] == 3
