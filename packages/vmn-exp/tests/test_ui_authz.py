"""Authorization: a role per route, enforced from request.state.principal."""
import tempfile
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.authz import ACTION_ROLES, effective_role, route_role
from vmn_exp.ui.auth.principal import ADMIN, EDITOR, VIEWER, Principal
from vmn_exp.core.real_io import RealRandom, real_io

ADMIN_ROUTES = {
    ("POST", "/api/v1/workspaces"),
    ("DELETE", "/api/v1/workspaces/{ws_name}"),
    ("GET", "/api/v1/tokens"),
    ("POST", "/api/v1/tokens"),
    ("DELETE", "/api/v1/tokens"),
    ("DELETE", "/api/v1/tokens/{token_id}"),
    ("GET", "/api/v1/audit"),
    ("GET", "/api/v1/audit/export"),
    ("DELETE", "/api/v1/workspaces/{ws_name}/reports/{rid}"),
    ("POST", "/api/v1/workspaces/{ws_name}/cache/resync"),
    ("GET", "/api/v1/workspaces/{ws_name}/cache/status"),
    ("GET", "/api/v1/diag"),
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
    return create_app(_manager(path), io=real_io(), auth=auth, **kw)


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


ML_EDITOR = [{"group": "ml", "workspace": "*", "role": EDITOR}]
WS_APPS = "/api/v1/workspaces/ws/apps"  # 404 when allowed (no such workspace)


def _cp(tmp_path):
    from vmn_exp.ui.control_plane import SQLiteControlPlane

    return SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))


def _get_as(tmp_path, authenticator, mappings, headers):
    from vmn_exp.ui.server import create_app

    app = create_app(_manager(tmp_path), io=real_io(), auth=AuthenticatorChain([authenticator]),
                     role_mappings=mappings)
    return TestClient(app, base_url="https://testserver").get(WS_APPS, headers=headers)


def _oidc_from_server_yml(tmp_path, mappings_yaml):
    import argparse

    from vmn_exp.ui.auth.oidc import OIDCAuthenticator
    from vmn_exp.ui.cli import build_server, server_app

    path = tmp_path / "server.yml"
    path.write_text(f"""
data_dir: {tmp_path / 'data'}
server: {{public_url: "https://vmn.acme.com/"}}
auth:
  oidc: {{issuer: "https://idp", client_id: c}}
  role_mappings: {mappings_yaml}
""")
    args = argparse.Namespace(host="127.0.0.1", port=8265, token=None, data_dir=None,
                              db=None, config=str(path), repo=None, store=None,
                              read_only=False, no_index=True, allowed_host=None)
    manager, cfg, cp = build_server(args, env={})
    app = server_app(manager, cfg, cp, args, io=real_io(), env={})
    return next(a for a in app.state.auth_chain.authenticators
                if isinstance(a, OIDCAuthenticator))


def test_oidc_principal_has_no_stored_roles(tmp_path):
    oidc = _oidc_from_server_yml(tmp_path, '[{group: ml, workspace: "*", role: admin}]')
    principal = oidc.principal_for({"sub": "u1", "name": "U", "groups": ["ml"]})
    assert principal.roles == {} and principal.groups == ("ml",)


def test_removed_role_mapping_drops_role_of_live_session(tmp_path):
    from vmn_exp.ui.auth.oidc import SESSION_COOKIE

    oidc = _oidc_from_server_yml(tmp_path, '[{group: ml, workspace: "*", role: editor}]')
    session_id = oidc.sessions.open(oidc.principal_for({"sub": "u1", "groups": ["ml"]}))
    cookie = {"Cookie": f"{SESSION_COOKIE}={session_id}"}
    assert _get_as(tmp_path, oidc, ML_EDITOR, cookie).status_code == 404
    assert _get_as(tmp_path, oidc, [], cookie).status_code == 403


def test_login_token_role_follows_current_mappings(tmp_path):
    from vmn_exp.ui.auth.tokens import ApiTokenAuthenticator, TokenService

    tokens = TokenService(_cp(tmp_path), time.time, random=RealRandom())
    secret, _ = tokens.create("login", {}, owner="oidc:u1", groups=("ml",))
    bearer = {"Authorization": f"Bearer {secret}"}
    authenticator = ApiTokenAuthenticator(tokens)
    assert _get_as(tmp_path, authenticator, ML_EDITOR, bearer).status_code == 404
    assert _get_as(tmp_path, authenticator, [], bearer).status_code == 403


def test_static_token_is_admin_everywhere(tmp_path):
    from vmn_exp.ui.server import create_app

    client = TestClient(create_app(_manager(tmp_path), io=real_io(), token="t"))
    headers = {**JSON, "Authorization": "Bearer t"}
    assert client.post("/api/v1/workspaces", json={}, headers=headers).status_code == 422


def test_no_auth_allows_everything(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.post("/api/v1/workspaces", json={}, headers=JSON).status_code == 422


def _job_in(app, workspace, org_id=0):
    from vmn_exp.ui.tenancy import org_context

    with org_context(org_id):  # what the org middleware binds for a request
        job, err = app.state.jobs.submit_call(workspace, ["exp", "tag"], lambda: "ok")
    assert err is None
    return f"/api/v1/jobs/{job['id']}"


def _with_job(tmp_path, workspace):
    app = _app(tmp_path, PRINCIPALS)
    return TestClient(app), _job_in(app, workspace)


def test_job_of_other_workspace_is_404_for_scoped_viewer(tmp_path):
    client, url = _with_job(tmp_path, "other")
    r = _call(client, "v", "GET", url)
    assert (r.status_code, r.json()["detail"]) == (404, "Job not found")


def test_job_visible_to_viewer_of_its_workspace(tmp_path):
    client, url = _with_job(tmp_path, "ws")
    assert _call(client, "v", "GET", url).status_code == 200


def test_job_visible_to_star_admin(tmp_path):
    client, url = _with_job(tmp_path, "other")
    assert _call(client, "a", "GET", url).status_code == 200


def test_job_visible_without_auth(tmp_path):
    app = _app(tmp_path)
    assert TestClient(app).get(_job_in(app, "other")).status_code == 200


def test_job_of_other_org_is_404_in_same_named_workspace(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    principals = {"Bearer o1": Principal("o1", "o1", {"ws": VIEWER}, org_id=1),
                  "Bearer o2": Principal("o2", "o2", {"ws": VIEWER}, org_id=2)}
    manager = WorkspaceManager(str(tmp_path), tenancy="multi")
    app = create_app(manager, io=real_io(), auth=AuthenticatorChain([_Fixed(principals)]))
    client, url = TestClient(app), _job_in(app, "ws", org_id=1)
    assert _call(client, "o1", "GET", url).status_code == 200
    assert _call(client, "o2", "GET", url).status_code == 404
