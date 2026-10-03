"""Plan 11 §4.6 over HTTP: ``POST .../cache/resync`` (``?full=1`` rebuilds),
``GET .../cache/status`` (admin), and ``vmn_cache_drift_total`` on
``/metrics``; a cache deleted under a running server heals on its own."""
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
V = "0.0.1-dev.abc.def"
WS = "/api/v1/workspaces/ws"


def _setup(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    open_storage(uri, area=RUNS).save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    client = TestClient(create_app(manager))
    assert client.get(f"{WS}/apps/{APP}/experiments").status_code == 200
    return client


def _until_idle(client, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"{WS}/cache/status").json()
        if status["state"] == "idle":
            return status
        time.sleep(0.05)
    raise AssertionError("rebuild did not finish")


def _cache_files(tmp_path):
    index_dir = os.path.join(tmp_path, "ui_data", "index")
    return [os.path.join(index_dir, f) for f in os.listdir(index_dir) if f.endswith(".sqlite")]


def test_status_lists_the_served_apps(tmp_path):
    status = _setup(tmp_path).get(f"{WS}/cache/status").json()
    assert status["workspace"] == "ws" and status["state"] == "idle"
    assert status["apps"][APP]["records"] == 1
    assert {"generation", "drift", "last_reconcile_at"} <= set(status["apps"][APP])
    assert {"journal_lag_sec", "progress", "rebuilds"} <= set(status)


def test_full_resync_rebuilds(tmp_path):
    client = _setup(tmp_path)
    r = client.post(f"{WS}/cache/resync?full=1", json={})
    assert r.status_code == 202, r.text
    status = _until_idle(client)
    assert status["rebuilds"] == 1 and status["progress"]["done"] == 1


def test_plain_resync_does_not_rebuild(tmp_path):
    client = _setup(tmp_path)
    assert client.post(f"{WS}/cache/resync", json={}).status_code == 202
    assert _until_idle(client)["rebuilds"] == 0


def test_a_deleted_cache_heals_without_a_restart(tmp_path):
    client = _setup(tmp_path)
    for path in _cache_files(tmp_path):
        os.remove(path)
    assert client.get(f"{WS}/apps/{APP}/experiments").status_code == 200
    status = _until_idle(client)
    assert status["rebuilds"] == 1 and status["last_rebuild_reason"] == "missing"
    assert _cache_files(tmp_path), os.listdir(os.path.join(tmp_path, "ui_data", "index"))
    rows = client.get(f"{WS}/apps/{APP}/experiments").json()
    assert rows


def test_unknown_workspace_is_404(tmp_path):
    client = _setup(tmp_path)
    assert client.get("/api/v1/workspaces/nope/cache/status").status_code == 404


def test_metrics_exposes_the_drift_counter(tmp_path):
    r = _setup(tmp_path).get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "# TYPE vmn_cache_drift_total counter" in r.text
    assert 'vmn_cache_drift_total{workspace="ws"} 0' in r.text
