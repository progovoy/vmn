"""API token management routes (admin), backed by the control plane."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.principal import ADMIN, EDITOR, Principal
from vmn_exp.ui.control_plane import SQLiteControlPlane

JSON = {"Content-Type": "application/json"}
A = {**JSON, "Authorization": "Bearer a"}
E = {**JSON, "Authorization": "Bearer e"}


class _Fixed:
    def authenticate(self, request):
        return {"Bearer a": Principal("u:admin", "Ada", {"*": ADMIN}),
                "Bearer e": Principal("u:ed", "Ed", {"*": EDITOR})}.get(
            request.headers.get("Authorization", ""))


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    return TestClient(create_app(WorkspaceManager(str(tmp_path / "ui")),
                                 auth=AuthenticatorChain([_Fixed()]), control_plane=cp))


def test_create_list_revoke(client):
    r = client.post("/api/v1/tokens", json={"name": "ci", "roles": {"ws": "viewer"},
                                            "ttl_sec": 3600}, headers=A)
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("vmnx_")
    assert body["record"]["owner"] == "u:admin" and "secret_hash" not in body["record"]
    listed = client.get("/api/v1/tokens", headers=A).json()
    assert [t["name"] for t in listed] == ["ci"] and "secret_hash" not in listed[0]
    token = body["token"]
    assert client.get("/api/v1/workspaces",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200
    tid = body["record"]["id"]
    assert client.delete(f"/api/v1/tokens/{tid}", headers=A).status_code == 204
    assert client.get("/api/v1/tokens", headers=A).json()[0]["revoked"] is True
    assert client.get("/api/v1/workspaces",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_bad_bodies_and_unknown_ids(client):
    assert client.post("/api/v1/tokens", json={"roles": {}}, headers=A).status_code == 422
    assert client.post("/api/v1/tokens", json={"name": "x", "roles": {"ws": "god"}},
                       headers=A).status_code == 422
    assert client.delete("/api/v1/tokens/nope", headers=A).status_code == 404


def test_tokens_need_admin(client):
    assert client.get("/api/v1/tokens", headers=E).status_code == 403
    assert client.post("/api/v1/tokens", json={"name": "x", "roles": {}},
                       headers=E).status_code == 403


def _control_plane(client):
    return client.app.state.control_plane


def test_delete_tokens_by_owner_is_admin_only(client):
    from vmn_exp.ui.auth.tokens import TokenService

    secret, _ = TokenService(_control_plane(client)).create("login", {}, owner="oidc:al")
    assert client.delete("/api/v1/tokens?owner=oidc:al", headers=E).status_code == 403
    assert TokenService(_control_plane(client)).verify(secret) is not None
    assert client.delete("/api/v1/tokens", headers=A).status_code == 422
    assert client.delete("/api/v1/tokens?owner=", headers=A).status_code == 422


def test_delete_tokens_by_owner_closes_sessions(client):
    from vmn_exp.ui.auth.sessions import SessionService
    from vmn_exp.ui.auth.tokens import TokenService

    cp = _control_plane(client)
    tokens, sessions = TokenService(cp), SessionService(cp)
    mine, _ = tokens.create("login", {}, owner="oidc:al", groups=("ml",))
    other, _ = tokens.create("login", {}, owner="oidc:bo", groups=("ml",))
    sid, bob_sid = sessions.open(Principal("oidc:al", "Al")), sessions.open(
        Principal("oidc:bo", "Bo"))
    r = client.delete("/api/v1/tokens?owner=oidc:al", headers=A)
    assert r.status_code == 200 and r.json() == {"tokens": 1, "sessions": 1}
    assert tokens.verify(mine) is None and sessions.principal(sid) is None
    assert tokens.verify(other) is not None and sessions.principal(bob_sid) is not None


def _mint(client, *names):
    for name in names:
        assert client.post("/api/v1/tokens", json={"name": name}, headers=A).status_code == 201


def test_tokens_limit_offset_with_total_header(client):
    _mint(client, "t0", "t1", "t2")
    r = client.get("/api/v1/tokens", params={"offset": 1, "limit": 1}, headers=A)
    assert [t["name"] for t in r.json()] == ["t1"]
    assert r.headers["X-Total-Count"] == "3"


def test_tokens_without_limit_is_the_full_list(client):
    _mint(client, "t0", "t1", "t2")
    r = client.get("/api/v1/tokens", headers=A)
    assert [t["name"] for t in r.json()] == ["t0", "t1", "t2"]
    assert "X-Total-Count" not in r.headers
