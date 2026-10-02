"""Audit log (plan 11 §6.2): control-plane table vmn_audit, an entry per mutation."""
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from vmn_exp.ui.audit import AuditLog
from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.authz import route_role
from vmn_exp.ui.auth.principal import ADMIN, VIEWER, Principal
from vmn_exp.ui.control_plane import SQLiteControlPlane

JSON = {"Content-Type": "application/json"}
ADMIN_P = Principal("u:admin", "Ada", {"*": ADMIN})
VIEWER_P = Principal("u:viewer", "Vic", {"*": VIEWER})


class _Fixed:
    def authenticate(self, request):
        return {"Bearer a": ADMIN_P, "Bearer v": VIEWER_P}.get(
            request.headers.get("Authorization", ""))


@pytest.fixture(params=["sqlite", "postgres"])
def cp(request, tmp_path):
    if request.param == "sqlite":
        return SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    from vmn_exp.ui.cache_pg import PostgresControlPlane

    return PostgresControlPlane(request.getfixturevalue("pg_dsn"))


def test_audit_log_appends_in_order(cp):
    clock = iter([10.0, 20.0, 30.0])
    log = AuditLog(cp, clock=lambda: next(clock))
    for action in ("a", "b", "c"):
        log.record(actor="u1", action=action)
    entries = log.entries()
    assert [e["action"] for e in entries][-3:] == ["a", "b", "c"]
    assert [e["ts"] for e in entries][-3:] == [10.0, 20.0, 30.0]
    assert len({e["id"] for e in entries}) == len(entries)


def test_audit_entries_page_newest_first(tmp_path):
    log = AuditLog(SQLiteControlPlane(str(tmp_path / "cp.sqlite3")))
    for i in range(5):
        log.record(actor="u", action=str(i))
    assert [e["action"] for e in log.page(offset=1, limit=2)] == ["3", "2"]


def _app(tmp_path, cp):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    return create_app(WorkspaceManager(str(tmp_path / "ui")),
                      auth=AuthenticatorChain([_Fixed()]), control_plane=cp)


def _mutating_routes(app):
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        if route_role(route) == VIEWER:
            continue
        for method in route.methods - {"GET", "HEAD"}:
            yield method, route.path


def _concrete(path):
    for name in ("app_tag", "verstr", "model_name", "alias", "version_n", "n",
                 "action", "job_id", "token_id", "filename:path", "path:path", "name:path"):
        path = path.replace("{" + name + "}", "x")
    return path.replace("{ws_name}", "ws")


def test_every_mutating_route_emits_an_audit_entry(tmp_path):
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    app = _app(tmp_path, cp)
    routes = sorted(_mutating_routes(app))
    assert ("POST", "/api/v1/tokens") in routes
    client = TestClient(app)
    for method, path in routes:
        client.request(method, _concrete(path), json={},
                       headers={**JSON, "Authorization": "Bearer a"})
    entries = AuditLog(cp).entries()
    seen = {e["action"] for e in entries}
    for method, path in routes:
        assert f"{method} {path}" in seen, (method, path)
    assert all(e["actor"] == "u:admin" and e["actor_name"] == "Ada" for e in entries)
    one = next(e for e in entries if e["action"] == "DELETE /api/v1/workspaces/{ws_name}")
    assert one["workspace"] == "ws" and one["path"] == "/api/v1/workspaces/ws"
    assert isinstance(one["status"], int)


def test_reads_are_not_audited_and_refusals_are(tmp_path):
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    client = TestClient(_app(tmp_path, cp))
    client.get("/api/v1/workspaces", headers={"Authorization": "Bearer a"})
    client.post("/api/v1/workspaces", json={}, headers={**JSON, "Authorization": "Bearer v"})
    entries = AuditLog(cp).entries()
    assert [(e["action"], e["status"], e["actor"]) for e in entries] == [
        ("POST /api/v1/workspaces", 403, "u:viewer")]


def test_audit_api_is_admin_and_exports_jsonl(tmp_path):
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    AuditLog(cp).record(actor="u1", action="login")
    client = TestClient(_app(tmp_path, cp))
    viewer = {"Authorization": "Bearer v"}
    admin = {"Authorization": "Bearer a"}
    assert client.get("/api/v1/audit", headers=viewer).status_code == 403
    body = client.get("/api/v1/audit", headers=admin).json()
    assert body["total"] == 1 and body["entries"][0]["action"] == "login"
    r = client.get("/api/v1/audit/export", headers=admin)
    assert r.status_code == 200 and "ndjson" in r.headers["content-type"]
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert [e["action"] for e in lines] == ["login"]


def test_audit_routes_without_control_plane_are_unavailable(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    client = TestClient(create_app(WorkspaceManager(str(tmp_path))))
    assert client.get("/api/v1/audit").status_code == 503
    assert client.get("/api/v1/tokens").status_code == 503
