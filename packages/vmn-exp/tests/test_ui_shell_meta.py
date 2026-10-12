"""GET /meta and /workspaces tell the shell who is signed in, with which role,
and how the server is deployed (plan 19 §2.1)."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.ui.auth import AuthenticatorChain  # noqa: E402
from vmn_exp.ui.auth.principal import ADMIN, EDITOR, VIEWER, Principal  # noqa: E402

PRINCIPALS = {
    "Bearer ws-viewer": Principal("u1", "Uma", {"ml": VIEWER}),
    "Bearer star-editor": Principal("u2", "Sam", {"*": EDITOR}),
}


class _Fixed:
    def __init__(self, principals):
        self.principals = principals

    def authenticate(self, request):
        return self.principals.get(request.headers.get("Authorization", ""))


def _manager(tmp_path, names=()):
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui"))
    for name in names:
        path = tmp_path / name
        os.makedirs(path / ".vmn")
        manager.attach_path(name, str(path))
    return manager


def _app(tmp_path, names=(), **kw):
    from vmn_exp.ui.server import create_app

    return create_app(_manager(tmp_path, names), **kw)


def _get(app, path, who=None):
    headers = {"Authorization": who} if who else {}
    r = TestClient(app).get(path, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_meta_without_auth(tmp_path):
    body = _get(_app(tmp_path), "/api/v1/meta")
    assert isinstance(body["version"], str)
    assert body["read_only"] is False
    assert body["mode"] == "standalone"
    assert body["control_plane"] is False
    assert body["auth"] == {
        "enabled": False, "token": False, "oidc": False, "login_url": None,
    }
    assert body["principal"] is None
    assert body["role"] is None


def test_meta_read_only_flag(tmp_path):
    assert _get(_app(tmp_path, read_only=True), "/api/v1/meta")["read_only"] is True


def test_meta_with_static_token(tmp_path):
    body = _get(_app(tmp_path, token="s3cret"), "/api/v1/meta", "Bearer s3cret")
    assert body["auth"]["enabled"] is True
    assert body["auth"]["token"] is True
    assert body["auth"]["oidc"] is False
    assert body["principal"] == {"id": "static-token", "name": "static token"}
    assert body["role"] == ADMIN


def test_meta_with_control_plane_is_configured(tmp_path):
    from vmn_exp.ui.control_plane import SQLiteControlPlane

    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    body = _get(_app(tmp_path, token="t", control_plane=cp), "/api/v1/meta", "Bearer t")
    assert body["mode"] == "configured"
    assert body["control_plane"] is True
    assert "api_tokens" not in body["auth"]


def test_meta_config_set_after_create_app_is_configured(tmp_path):
    app = _app(tmp_path)
    assert _get(app, "/api/v1/meta")["mode"] == "standalone"
    app.state.config = object()  # what server_app does after create_app
    assert _get(app, "/api/v1/meta")["mode"] == "configured"


def test_meta_vmn_exp_version_is_a_string(tmp_path):
    assert isinstance(_get(_app(tmp_path), "/api/v1/meta")["vmn_exp_version"], str)


@pytest.fixture
def uncached_version():
    """Forget the process-wide vmn-exp version before and after the test."""
    from vmn_exp.ui import shell_meta

    shell_meta._vmn_exp_version.cache_clear()
    yield
    shell_meta._vmn_exp_version.cache_clear()


def test_meta_vmn_exp_version_null_when_not_installed(tmp_path, monkeypatch, uncached_version):
    from importlib import metadata

    def _missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", _missing)
    assert _get(_app(tmp_path), "/api/v1/meta")["vmn_exp_version"] is None


def test_meta_vmn_exp_version_is_read_once_per_process(tmp_path, monkeypatch, uncached_version):
    from importlib import metadata

    calls = []
    real = metadata.version
    monkeypatch.setattr(metadata, "version", lambda name: calls.append(name) or real(name))
    app = _app(tmp_path)
    _get(app, "/api/v1/meta")
    _get(app, "/api/v1/meta")
    assert calls.count("vmn-exp") == 1


def test_meta_role_null_for_a_per_workspace_principal(tmp_path):
    auth = AuthenticatorChain([_Fixed(PRINCIPALS)])
    body = _get(_app(tmp_path, ["ml"], auth=auth), "/api/v1/meta", "Bearer ws-viewer")
    assert body["auth"]["enabled"] is True
    assert body["principal"] == {"id": "u1", "name": "Uma"}
    assert body["role"] is None


def _roles(body):
    return {ws["name"]: ws["role"] for ws in body}


def test_workspaces_role_null_without_auth(tmp_path):
    assert _roles(_get(_app(tmp_path, ["ml", "eval"]), "/api/v1/workspaces")) == {
        "ml": None, "eval": None,
    }


def test_workspaces_role_per_workspace(tmp_path):
    app = _app(tmp_path, ["ml", "eval"], auth=AuthenticatorChain([_Fixed(PRINCIPALS)]))
    assert _roles(_get(app, "/api/v1/workspaces", "Bearer ws-viewer")) == {
        "ml": VIEWER, "eval": None,
    }


def test_workspaces_role_from_star(tmp_path):
    app = _app(tmp_path, ["ml", "eval"], auth=AuthenticatorChain([_Fixed(PRINCIPALS)]))
    assert _roles(_get(app, "/api/v1/workspaces", "Bearer star-editor")) == {
        "ml": EDITOR, "eval": EDITOR,
    }
