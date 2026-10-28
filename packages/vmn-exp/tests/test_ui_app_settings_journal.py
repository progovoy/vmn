"""Plan 28 A0 with the background refresher: a store workspace's stale window
comes from its settings, and another host's settings write reaches the server
through the store's journal, well inside the cache's own recheck window."""
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings_store import write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui import experiment_source  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


@pytest.fixture
def served(tmp_path, monkeypatch):
    """``(client, the store as another host opens it)``."""
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    monkeypatch.setattr(experiment_source, "SETTINGS_RECHECK_SEC", 3600)
    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    v = "0.0.1-dev.0000abcd.0"
    storage.save(APP, v, {"verstr": v, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    app = create_app(manager, background_refresh=True)
    yield TestClient(app), storage
    app.state.refresher.stop()


def _poll(client, path, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    body = client.get(path).json()
    while not predicate(body) and time.monotonic() < deadline:
        time.sleep(0.1)
        body = client.get(path).json()
    return body


def test_the_stale_window_comes_from_the_store_settings(served):
    client, storage = served
    write_settings(storage, APP, "ui: {stale_after_min: 30}\n")
    body = _poll(client, f"{BASE}/experiments-status",
                 lambda b: (b.get("freshness") or {}).get("stale_after_sec") == 1800)
    assert body["freshness"]["stale_after_sec"] == 1800


def test_another_hosts_write_reaches_the_server_through_the_journal(served):
    client, storage = served
    assert client.get(f"{BASE}/metrics-schema").json() == {}
    write_settings(storage, APP, "metrics: {acc: {goal: max}}\n")
    body = _poll(client, f"{BASE}/metrics-schema", lambda b: b != {})
    assert body == {"acc": {"goal": "max"}}
