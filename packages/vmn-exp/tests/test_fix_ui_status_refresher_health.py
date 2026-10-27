"""An app's experiments-status (and apps-status) carries its background
refresher's health (``refresher``), so the dashboard and a load balancer see
an index that stopped refreshing; an inline refresher reports none."""
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
STATUS = f"/api/v1/workspaces/ws/apps/{APP}/experiments-status"
HEALTH_KEYS = {"alive", "failing", "failures", "since_refresh_sec", "refreshing_sec",
               "last_error"}


def _client(tmp_path, background_refresh):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    v = "0.0.1-dev.0000abcd.0"
    open_storage(uri, area=RUNS).save(APP, v, {"verstr": v, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    app = create_app(manager, background_refresh=background_refresh)
    return app, TestClient(app)


@pytest.fixture
def background(tmp_path):
    app, client = _client(tmp_path, background_refresh=True)
    yield client
    app.state.refresher.stop()


def _wait_for_status(client, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    body = client.get(STATUS).json()
    while not predicate(body) and time.monotonic() < deadline:
        time.sleep(0.05)
        body = client.get(STATUS).json()
    return body


def test_experiments_status_reports_a_healthy_refresher(background):
    body = _wait_for_status(background, lambda b: b.get("refresher", {}).get("alive"))
    health = body["refresher"]
    assert set(health) == HEALTH_KEYS
    assert health["alive"] and not health["failing"] and health["last_error"] is None


def test_experiments_status_reports_a_failing_refresher(background, monkeypatch):
    background.get(STATUS)

    def broken(self):
        raise RuntimeError("storage went away")

    monkeypatch.setattr(ExperimentIndex, "refresh", broken)
    body = _wait_for_status(background, lambda b: b.get("refresher", {}).get("failing"))
    assert body["refresher"]["failing"]
    assert "storage went away" in body["refresher"]["last_error"]


def test_apps_status_carries_each_apps_refresher(background):
    background.get(STATUS)
    body = background.get("/api/v1/workspaces/ws/apps-status").json()
    assert set(body[APP]["refresher"]) == HEALTH_KEYS


def test_an_inline_refresher_reports_no_health(tmp_path):
    _, client = _client(tmp_path, background_refresh=False)
    assert "refresher" not in client.get(STATUS).json()
