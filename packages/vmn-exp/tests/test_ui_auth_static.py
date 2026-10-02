"""Static --token authentication through the Authenticator chain."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.ui.auth.principal import ADMIN, Principal
from vmn_exp.ui.auth.static import StaticTokenAuthenticator


class _Req:
    def __init__(self, headers):
        self.headers = headers
        self.cookies = {}


def _app(tmp_path, **kw):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app = create_app(WorkspaceManager(str(tmp_path / "ui")), **kw)

    @app.get("/api/v1/_whoami")
    def _whoami(request: fastapi.Request):
        p = request.state.principal
        return {"id": p.id, "roles": p.roles} if p else None

    # Ahead of the SPA/API catch-alls create_app registered last.
    app.router.routes.insert(0, app.router.routes.pop())
    return app


def test_static_token_maps_to_implicit_admin():
    auth = StaticTokenAuthenticator("s3cret")
    p = auth.authenticate(_Req({"Authorization": "Bearer s3cret"}))
    assert isinstance(p, Principal)
    assert p.role_in("any-workspace") == ADMIN
    assert auth.authenticate(_Req({"Authorization": "Bearer nope"})) is None
    assert auth.authenticate(_Req({})) is None


def test_create_app_token_attaches_principal(tmp_path):
    client = TestClient(_app(tmp_path, token="s3cret"))
    assert client.get("/api/v1/_whoami").status_code == 401
    r = client.get("/api/v1/_whoami", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json() == {"id": "static-token", "roles": {"*": ADMIN}}


def test_no_auth_leaves_api_open_with_no_principal(tmp_path):
    client = TestClient(_app(tmp_path))
    r = client.get("/api/v1/_whoami")
    assert r.status_code == 200 and r.json() is None


def test_non_api_paths_need_no_credential(tmp_path):
    client = TestClient(_app(tmp_path, token="s3cret"))
    assert client.get("/api/v1/workspaces").status_code == 401
    assert client.get("/").status_code != 401
