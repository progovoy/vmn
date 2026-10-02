"""Authorization: a role per route, enforced from request.state.principal."""
import tempfile

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.authz import ACTION_ROLES, effective_role, route_role
from vmn_exp.ui.auth.principal import ADMIN, EDITOR, VIEWER, Principal

ADMIN_ROUTES = {
    ("POST", "/api/v1/workspaces"),
    ("DELETE", "/api/v1/workspaces/{ws_name}"),
    ("GET", "/api/v1/tokens"),
    ("POST", "/api/v1/tokens"),
    ("DELETE", "/api/v1/tokens/{token_id}"),
    ("GET", "/api/v1/audit"),
    ("GET", "/api/v1/audit/export"),
}
READ_POSTS = {"/api/v1/workspaces/{ws_name}/apps/{app_tag}/series"}
RANK = {VIEWER: 0, EDITOR: 1, ADMIN: 2}
PRINCIPALS = {
    "Bearer v": Principal("v", "v", {"ws": VIEWER}),
    "Bearer e": Principal("e", "e", {"ws": EDITOR}),
    "Bearer a": Principal("a", "a", {"*": ADMIN}),
    "Bearer g": Principal("g", "g", {}, groups=("ml",)),
}
JSON = {"Content-Type": "application/json"}


class _Fixed:
    """Maps an Authorization header to a fixed principal."""

    def __init__(self, principals):
        self.principals = principals

    def authenticate(self, request):
        return self.principals.get(request.headers.get("Authorization", ""))


def _manager(path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    return WorkspaceManager(str(path))


def _app(path, principals=None, **kw):
    from vmn_exp.ui.server import create_app

    auth = AuthenticatorChain([_Fixed(principals)]) if principals else None
    return create_app(_manager(path), auth=auth, **kw)


def _api_routes(app):
    return [
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/v1")
    ]


def _expected(method, path):
    if (method, path) in ADMIN_ROUTES:
        return ADMIN
    if method == "GET" or path in READ_POSTS:
        return VIEWER
    return EDITOR


def _all_routes():
    with tempfile.TemporaryDirectory() as d:
        app = _app(d)
        return sorted((m, r.path) for r in _api_routes(app) for m in r.methods)


def _concrete(path):
    for name in ("app_tag", "verstr", "model_name", "alias", "version_n", "n",
                 "action", "job_id", "token_id", "filename:path", "path:path", "name:path"):
        path = path.replace("{" + name + "}", "x")
    return path.replace("{ws_name}", "ws")


def _client(tmp_path, **kw):
    return TestClient(_app(tmp_path, PRINCIPALS, **kw))


def _call(client, who, method, path, body=None):
    headers = {**JSON, "Authorization": f"Bearer {who}"}
    return client.request(method, path, headers=headers, json=body)


def test_every_route_declares_the_expected_role(tmp_path):
    routes = _api_routes(_app(tmp_path))
    assert routes
    for route in routes:
        role = route_role(route)
        assert role is not None, f"{route.path} declares no role"
        for method in route.methods:
            assert role == _expected(method, route.path), (method, route.path)


@pytest.mark.parametrize("method,path", _all_routes())
def test_route_role_matrix(tmp_path, method, path):
    client = _client(tmp_path)
    need = _expected(method, path)
    url = _concrete(path)
    for who, role in (("v", VIEWER), ("e", EDITOR), ("a", ADMIN)):
        status = _call(client, who, method, url, {}).status_code
        if RANK[role] < RANK[need]:
            assert status == 403, (who, method, path, status)
        else:
            assert status not in (401, 403), (who, method, path, status)
    assert _call(client, "nobody", method, url, {}).status_code == 401


def test_action_roles_prune_is_admin():
    assert ACTION_ROLES["prune"] == ADMIN


def test_viewer_cannot_run_actions_editor_cannot_prune(tmp_path):
    client = _client(tmp_path)
    path = "/api/v1/workspaces/ws/apps/x/actions/{}"
    assert _call(client, "v", "POST", path.format("exp_tag"), {}).status_code == 403
    assert _call(client, "e", "POST", path.format("exp_tag"), {}).status_code != 403
    assert _call(client, "e", "POST", path.format("prune"), {"keep": 1}).status_code == 403
    assert _call(client, "a", "POST", path.format("prune"), {"keep": 1}).status_code != 403


def test_effective_role_merges_principal_and_group_mappings():
    p = Principal("u", "u", {"ws1": VIEWER}, groups=("ml",))
    maps = [
        {"group": "ml", "workspace": "*", "role": EDITOR},
        {"group": "ops", "workspace": "ws1", "role": ADMIN},
    ]
    assert effective_role(p, "ws1", maps) == EDITOR
    assert effective_role(p, "other", maps) == EDITOR
    assert effective_role(Principal("v", "v", {"ws1": VIEWER}), "ws2", maps) is None


def test_viewer_without_role_in_workspace_is_refused(tmp_path):
    client = _client(tmp_path)
    assert _call(client, "v", "GET", "/api/v1/workspaces/other/apps").status_code == 403
    assert _call(client, "v", "GET", "/api/v1/workspaces").status_code == 200


def test_group_mappings_from_create_app(tmp_path):
    maps = [{"group": "ml", "workspace": "*", "role": EDITOR}]
    client = _client(tmp_path, role_mappings=maps)
    assert _call(client, "g", "GET", "/api/v1/workspaces/ws/apps").status_code == 404
    assert _call(client, "g", "POST", "/api/v1/workspaces", {}).status_code == 403
    no_maps = _client(tmp_path)
    assert _call(no_maps, "g", "GET", "/api/v1/workspaces/ws/apps").status_code == 403


def test_static_token_is_admin_everywhere(tmp_path):
    from vmn_exp.ui.server import create_app

    client = TestClient(create_app(_manager(tmp_path), token="t"))
    headers = {**JSON, "Authorization": "Bearer t"}
    assert client.post("/api/v1/workspaces", json={}, headers=headers).status_code == 422


def test_no_auth_allows_everything(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.post("/api/v1/workspaces", json={}, headers=JSON).status_code == 422
