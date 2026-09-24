"""vmn ui JSON rendering: orjson when available, NaN-safe either way, ETags,
and heavy handlers answer pre-rendered bytes (no encoding on the event loop)."""
import datetime
import gzip
import json

import pytest

pytest.importorskip("fastapi")
from starlette.requests import Request
from starlette.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.ui import responses
from version_stamp.ui.responses import SafeJSONResponse, json_response

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _request(headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def _strict(body):
    return json.loads(body, parse_constant=lambda c: pytest.fail(f"bare {c}"))


@pytest.fixture(params=["orjson", "stdlib"])
def renderer(request, monkeypatch):
    if request.param == "orjson":
        pytest.importorskip("orjson")
    else:
        monkeypatch.setattr(responses, "orjson", None)
    return request.param


def test_non_finite_floats_render_as_null(renderer):
    payload = {"a": float("nan"), "b": [1.5, float("inf"), {"c": float("-inf")}]}
    body = SafeJSONResponse(payload).body
    assert _strict(body) == {"a": None, "b": [1.5, None, {"c": None}]}


def test_datetimes_and_non_ascii_render(renderer):
    when = datetime.datetime(2026, 1, 2, 3, 4, 5)
    body = SafeJSONResponse({"t": when, "n": "héllo"}).body
    assert _strict(body) == {"t": "2026-01-02T03:04:05", "n": "héllo"}


def test_orjson_is_used_when_installed(monkeypatch):
    pytest.importorskip("orjson")
    calls = []
    real = responses.orjson.dumps

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(responses.orjson, "dumps", spy)
    SafeJSONResponse({"x": 1})
    assert calls


def test_json_response_sets_no_cache_and_an_etag():
    r = json_response({"x": 1}, request=_request())
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["etag"].startswith('"')
    assert _strict(r.body) == {"x": 1}


def test_json_response_uses_a_given_etag():
    r = json_response({"x": 1}, etag="abc")
    assert r.headers["etag"] == '"abc"'


def test_matching_if_none_match_is_a_304_without_body():
    first = json_response({"x": 1}, request=_request())
    tag = first.headers["etag"]
    for header in (tag, f'"other", {tag}', f"W/{tag}", "*"):
        r = json_response({"x": 1}, request=_request({"If-None-Match": header}))
        assert r.status_code == 304, header
        assert r.body == b""
        assert r.headers["etag"] == tag


def test_stale_if_none_match_gets_the_full_body():
    r = json_response({"x": 2}, request=_request({"If-None-Match": '"nope"'}))
    assert r.status_code == 200
    assert _strict(r.body) == {"x": 2}


def test_large_body_is_gzipped_in_the_handler_when_accepted():
    payload = {"rows": [{"i": i, "name": "row"} for i in range(500)]}
    r = json_response(payload, request=_request({"Accept-Encoding": "gzip, br"}))
    assert r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()
    assert _strict(gzip.decompress(r.body)) == payload


def test_body_is_not_gzipped_when_not_accepted():
    payload = {"rows": [{"i": i} for i in range(500)]}
    r = json_response(payload, request=_request())
    assert "content-encoding" not in r.headers
    assert _strict(r.body) == payload


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")
    storage.save(APP, "1.0.0-dev.a", {"verstr": "1.0.0-dev.a", "timestamp": "t"}, {})
    for i in range(30):
        storage.append_log_entry(
            APP,
            "1.0.0-dev.a",
            "w",
            {"timestamp": f"2026-01-01T00:00:{i:02d}Z", "type": "metrics", "step": i,
             "values": {"loss": float("nan") if i == 3 else i / 10}},
        )

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager))


@pytest.mark.parametrize("path", ["/1.0.0-dev.a", "/1.0.0-dev.a/log"])
def test_heavy_handlers_skip_fastapis_encoder(ws, monkeypatch, path):
    import fastapi.routing

    def no_encoding(*args, **kwargs):
        raise AssertionError("heavy handlers must return pre-rendered bytes")

    monkeypatch.setattr(fastapi.routing, "jsonable_encoder", no_encoding)
    monkeypatch.setattr(fastapi.routing, "serialize_response", no_encoding)
    r = ws.get(BASE + path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    _strict(r.text)


def test_detail_answers_304_when_unchanged(ws):
    r = ws.get(BASE + "/1.0.0-dev.a/log")
    again = ws.get(BASE + "/1.0.0-dev.a/log", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
