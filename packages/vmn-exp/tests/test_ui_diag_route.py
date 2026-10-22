"""GET /api/v1/diag: admin-only, and answering while every pool thread is busy."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.principal import ADMIN, VIEWER, Principal

APP = "app"
DIAG = "/api/v1/diag"
TOKEN = "diag-t0ken-SECRET"
BLOCKED = 48  # more than the default 40-thread pool


def _manager(tmp_path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = open_storage(root=local_store_root(str(root)), area="runs")
    storage.save(APP, "1.0.0-dev.a", {"verstr": "1.0.0-dev.a",
                                      "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return manager


class _Fixed:
    def __init__(self, principals):
        self.principals = principals

    def authenticate(self, request):
        return self.principals.get(request.headers.get("Authorization", ""))


def test_diag_is_admin_only(tmp_path):
    from vmn_exp.ui.server import create_app

    auth = AuthenticatorChain([_Fixed({
        "Bearer v": Principal("v", "v", {"*": VIEWER}),
        "Bearer a": Principal("a", "a", {"*": ADMIN}),
    })])
    with TestClient(create_app(_manager(tmp_path), auth=auth)) as client:
        assert client.get(DIAG).status_code == 401
        assert client.get(DIAG, headers={"Authorization": "Bearer v"}).status_code == 403
        answer = client.get(DIAG, headers={"Authorization": "Bearer a"})
    assert answer.status_code == 200
    assert answer.json()["format"] == 1


def _call_quietly(client, path, headers):
    try:
        client.get(path, headers=headers)
    except Exception:
        pass


def test_diag_answers_while_the_default_pool_is_saturated(tmp_path, monkeypatch):
    from vmn_exp.ui import server

    release, entered = threading.Event(), []

    def blocked_meta(*args, **kwargs):
        entered.append(1)
        release.wait(30)
        return {}

    monkeypatch.setattr(server, "meta_payload", blocked_meta)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(server.create_app(_manager(tmp_path), token=TOKEN)) as client:
        slow = [threading.Thread(target=_call_quietly, args=(client, "/api/v1/meta", headers),
                                 daemon=True) for _ in range(BLOCKED)]
        try:
            for t in slow:
                t.start()
            deadline = time.monotonic() + 10
            while len(entered) < 40 and time.monotonic() < deadline:
                time.sleep(0.02)
            time.sleep(0.3)
            answered = []
            asker = threading.Thread(
                target=lambda: answered.append(client.get(DIAG, headers=headers)), daemon=True)
            asker.start()
            asker.join(5)
            assert answered and answered[0].status_code == 200, (
                f"diag waited behind {len(entered)} blocked requests")
        finally:
            release.set()
            for t in slow:
                t.join(30)
    dump = answered[0].json()
    pool = dump["sections"]["pools"]["default"]
    assert pool["borrowed"] == pool["total"] == 40
    assert pool["waiting"] >= 1
    flight = dump["sections"]["requests"]["in_flight"]
    assert sum(r["route"] == "/api/v1/meta" for r in flight) >= 40
    assert TOKEN not in answered[0].text


def test_the_pools_section_carries_the_slow_read_limiter(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.slow_reads import SLOW_READ_THREADS

    with TestClient(create_app(_manager(tmp_path))) as client:
        pools = client.get(DIAG).json()["sections"]["pools"]
    assert pools["slow_read"]["total"] == SLOW_READ_THREADS
    assert pools["slow_read"]["borrowed"] == 0


def test_the_indexes_section_reports_each_watched_app(tmp_path):
    from vmn_exp.ui.server import create_app

    app = create_app(_manager(tmp_path), background_refresh=True)
    with TestClient(app) as client:
        assert client.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments").status_code == 200
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            indexes = client.get(DIAG).json()["sections"]["indexes"]["watched"]
            if indexes and indexes[0]["last_refresh_sec"] is not None:
                break
            time.sleep(0.05)
        app.state.refresher.stop()
    entry = [i for i in indexes if i["app"] == APP][0]
    assert entry["rows"] == 1
    assert entry["loading"] is None
    assert entry["generation"] >= 1
    assert entry["refresher_alive"] is True
    assert entry["since_publish_sec"] >= 0
    assert entry["since_refresh_sec"] >= 0
    assert entry["last_refresh_sec"] >= 0
    assert {"journaled", "full_listing_due", "refreshing", "records"} <= set(entry)
