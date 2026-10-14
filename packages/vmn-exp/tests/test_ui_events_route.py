"""``GET .../apps/{app}/events`` over HTTP (plan 23 S5): a text/event-stream
served from the background refresher, a 404 without one (the client polls),
a 503 past the stream cap, and the /api auth guard."""
import json
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.open import open_storage

from vmn_exp.ui import live_events

APP = "app"
EVENTS = f"/api/v1/workspaces/ws/apps/{APP}/events"


def _app(tmp_path, **opts):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = open_storage(root=local_store_root(str(root)), area="runs")

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return create_app(manager, **opts), storage


def _run(storage, i):
    verstr = f"1.0.0-dev.r{i:04d}"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    return verstr


@pytest.fixture
def short_streams(monkeypatch):
    monkeypatch.setattr(live_events, "MAX_STREAM_SEC", 2.5)
    monkeypatch.setattr(live_events, "COALESCE_SEC", 0.1)


@pytest.fixture
def background(tmp_path, short_streams):
    app, storage = _app(tmp_path, background_refresh=True)
    yield app, storage
    app.state.refresher.stop()


def _events(body):
    out = []
    for chunk in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in chunk.split("\n") if ": " in line
                      and not line.startswith(":"))
        if "event" in fields:
            out.append((fields["event"], json.loads(fields["data"])))
    return out


def test_a_new_run_is_pushed_as_a_change_event(background):
    app, storage = background
    _run(storage, 0)
    client = TestClient(app)
    client.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments")  # warm the index
    threading.Timer(0.6, _run, (storage, 1)).start()

    res = client.get(EVENTS, params={"scope": "top"})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"
    assert "content-encoding" not in res.headers
    kinds = _events(res.text)
    assert kinds[0][0] == "hello"
    changes = [data for kind, data in kinds if kind == "change"]
    assert changes and changes[0]["changed"]["rows"] >= 1


def test_without_a_background_refresher_there_is_no_stream(tmp_path, short_streams):
    app, _ = _app(tmp_path)

    res = TestClient(app).get(EVENTS)

    assert res.status_code == 404
    assert res.json()["reason"] == "no_live_events"


def test_streams_past_the_cap_are_refused_and_slots_come_back(background, monkeypatch):
    app, storage = background
    _run(storage, 0)
    client = TestClient(app)
    app.state.event_slots.limit = 0

    refused = client.get(EVENTS)

    assert refused.status_code == 503
    app.state.event_slots.limit = 1
    start = time.monotonic()
    assert client.get(EVENTS).status_code == 200
    assert time.monotonic() - start < 10
    assert app.state.event_slots.active == 0


def test_a_scope_must_be_a_safe_segment(background):
    app, _ = background

    assert TestClient(app).get(EVENTS, params={"scope": "../x"}).status_code == 400


def test_events_need_the_token_like_any_api_route(tmp_path, short_streams):
    app, _ = _app(tmp_path, background_refresh=True, token="s3cret")
    try:
        client = TestClient(app)
        assert client.get(EVENTS).status_code == 401
        ok = client.get(EVENTS, headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
    finally:
        app.state.refresher.stop()


def test_a_foreign_host_is_refused(background):
    app, _ = background

    res = TestClient(app).get(EVENTS, headers={"Host": "evil.example"})

    assert res.status_code in (400, 403)
