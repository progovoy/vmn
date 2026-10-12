"""A 401 from /api names the sign-in methods the server accepts, never a
secret (plan 19 §2.1), so the shell can render its sign-in page."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.ui.auth import AuthenticatorChain  # noqa: E402

SECRET = "s3cret-token-value"


class _OidcStub:
    """Looks like an OIDC authenticator: it serves routes and knows nobody."""

    def router(self):
        return fastapi.APIRouter()

    def authenticate(self, request):
        return None


def _client(tmp_path, token=None, oidc=False):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    auth = AuthenticatorChain([_OidcStub()]) if oidc else None
    return TestClient(create_app(WorkspaceManager(str(tmp_path / "ui")), token=token, auth=auth))


def _unauthorized(client):
    r = client.get("/api/v1/workspaces")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    return r


def test_token_only(tmp_path):
    r = _unauthorized(_client(tmp_path, token=SECRET))
    assert r.json() == {
        "detail": "Unauthorized",
        "auth": {"token": True, "oidc": False, "login_url": None},
    }


def test_oidc_only(tmp_path):
    r = _unauthorized(_client(tmp_path, oidc=True))
    assert r.json()["auth"] == {"token": False, "oidc": True, "login_url": "/auth/login"}


def test_token_and_oidc(tmp_path):
    r = _unauthorized(_client(tmp_path, token=SECRET, oidc=True))
    assert r.json()["auth"] == {"token": True, "oidc": True, "login_url": "/auth/login"}


def test_a_wrong_token_gets_the_same_hints(tmp_path):
    client = _client(tmp_path, token=SECRET)
    r = client.get("/api/v1/meta", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json()["auth"]["token"] is True


def test_no_secret_in_the_body(tmp_path):
    r = _unauthorized(_client(tmp_path, token=SECRET, oidc=True))
    assert SECRET not in r.text
