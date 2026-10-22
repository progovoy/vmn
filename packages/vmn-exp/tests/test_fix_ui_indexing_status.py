"""While a store's index loads chunk by chunk, an app's experiments-status
says how far it is (``indexing``), so the dashboard can show it; a loaded
index says nothing."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
moto = pytest.importorskip("moto")
import boto3  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import vmn_exp.core.index as index_module  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "app"
CHUNK = 5
N = 12
STATUS = f"/api/v1/workspaces/ws/apps/{APP}/experiments-status"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", CHUNK)
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
        app = create_app(manager, background_refresh=True)
        yield TestClient(app)
        app.state.refresher.stop()


def test_experiments_status_reports_an_index_still_loading(store, monkeypatch):
    release, lock, loads = threading.Event(), threading.Lock(), [0]
    real = S3SnapshotStorage.load_file

    def gated(self, app_name, verstr, filename):
        if filename == "metadata.yml":
            with lock:
                loads[0] += 1
                n = loads[0]
            if n > CHUNK:
                release.wait(10)
        return real(self, app_name, verstr, filename)

    monkeypatch.setattr(S3SnapshotStorage, "load_file", gated)
    loading = store.get(STATUS).json()
    release.set()
    deadline, done = time.monotonic() + 10, loading
    while "indexing" in done and time.monotonic() < deadline:
        time.sleep(0.1)
        done = store.get(STATUS).json()

    assert loading["indexing"] == {"loaded": CHUNK, "total": N}
    assert "indexing" not in done and done["total"] == N
