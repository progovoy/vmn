"""Org middleware: the principal's org bound per request in multi tenancy."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from vmn_exp.ui.auth.principal import Principal
from vmn_exp.ui.tenancy import install_org_middleware


def _app(principal, tenancy):
    app = FastAPI()
    install_org_middleware(app, tenancy)

    @app.middleware("http")
    async def authn(request: Request, call_next):
        request.state.principal = principal
        return await call_next(request)

    @app.get("/api/x")
    def x(request: Request):
        return {"org": request.state.org_id}

    return app


def test_principal_org_is_bound_to_the_request():
    client = TestClient(_app(Principal("u", "u", org_id=7), "multi"))
    assert client.get("/api/x").json() == {"org": 7}


def test_multi_tenancy_refuses_a_principal_without_org():
    client = TestClient(_app(Principal("u", "u"), "multi"))
    assert client.get("/api/x").status_code == 403


def test_single_tenancy_uses_org_zero():
    client = TestClient(_app(Principal("u", "u"), "single"))
    assert client.get("/api/x").json() == {"org": 0}


def test_create_app_binds_orgs_in_multi_tenancy(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path), tenancy="multi")
    client = TestClient(create_app(manager, token="t"))
    r = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403
