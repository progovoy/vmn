"""Credentials resolve their own org under row-level security (plan 11 §6.3):
auth runs before a request's org is known, so a token or session id is
looked up across orgs and the request then runs in the credential's org."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.ui.auth.principal import Principal  # noqa: E402
from vmn_exp.ui.auth.sessions import SessionService  # noqa: E402
from vmn_exp.ui.auth.tokens import TokenService  # noqa: E402
from vmn_exp.ui.tenancy import current_org, org_context  # noqa: E402


@pytest.fixture
def cp(pg_rls_dsn):
    from vmn_exp.ui.control_plane_pg import PostgresControlPlane

    return PostgresControlPlane(pg_rls_dsn)


def _token(cp, org, name):
    with org_context(org):
        return TokenService(cp).create(name, {"*": "admin"})[0]


def test_a_token_resolves_its_own_org(cp):
    token = _token(cp, 2, "t2")
    assert current_org() is None
    principal = TokenService(cp).verify(token)
    assert principal is not None and principal.org_id == 2


def test_an_unknown_token_is_refused(cp):
    _token(cp, 2, "t2")
    assert TokenService(cp).verify("vmnx_0000000000000000_nope") is None


def test_a_session_resolves_its_own_org(cp):
    session_id = SessionService(cp).open(Principal("oidc:a", "a", {"*": "admin"}, org_id=2))
    principal = SessionService(cp).principal(session_id)
    assert principal is not None and principal.org_id == 2
    with org_context(2):
        assert len(cp.list("session")) == 1
    with org_context(0):
        assert cp.list("session") == []


def _client(tmp_path, cp, token):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui"), tenancy="multi")
    app = create_app(manager, control_plane=cp)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_each_org_token_sees_only_its_org(tmp_path, cp):
    t1, t2 = _token(cp, 1, "t1"), _token(cp, 2, "t2")
    names = {
        token: [r["name"] for r in _client(tmp_path, cp, token).get("/api/v1/tokens").json()]
        for token in (t1, t2)
    }
    assert names == {t1: ["t1"], t2: ["t2"]}
