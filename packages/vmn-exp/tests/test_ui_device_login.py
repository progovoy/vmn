"""``vmn-exp login``: OIDC device flow through the server, a 0600 credentials file."""
import json
import os
import stat

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from test_ui_auth_oidc import ISSUER, _jwt

from vmn_exp.cli import login as login_cli
from vmn_exp.ui.audit import AuditLog
from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.oidc import OIDCAuthenticator, OIDCConfig
from vmn_exp.ui.auth.principal import EDITOR
from vmn_exp.ui.control_plane import SQLiteControlPlane

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SERVER = "https://vmn.example"


class FakeDeviceIdP:
    """Discovery, device authorization and a token endpoint pending N polls."""

    def __init__(self, pending_polls=1, claims=None):
        self.pending_polls = pending_polls
        self.claims = claims or {"sub": "u1", "name": "Alice", "groups": ["ml-team"]}
        self.approved = False

    def get_json(self, url):
        assert url == f"{ISSUER}/.well-known/openid-configuration"
        return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "device_authorization_endpoint": f"{ISSUER}/device"}

    def post_form(self, url, data):
        if url == f"{ISSUER}/device":
            assert data["client_id"] == "vmn-exp" and "openid" in data["scope"]
            return {"device_code": "idp-dev-1", "user_code": "ABCD-EFGH",
                    "verification_uri": f"{ISSUER}/activate",
                    "interval": 0, "expires_in": 600}
        assert url == f"{ISSUER}/token"
        assert data["grant_type"] == DEVICE_GRANT and data["device_code"] == "idp-dev-1"
        if self.pending_polls:
            self.pending_polls -= 1
            return {"error": "authorization_pending"}
        claims = {"iss": ISSUER, "aud": "vmn-exp", "exp": 4e9, **self.claims}
        return {"access_token": "at", "id_token": _jwt(claims)}


def _server(tmp_path, idp):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    config = OIDCConfig(issuer=ISSUER, client_id="vmn-exp",
                        redirect_uri=f"{SERVER}/auth/callback",
                        role_mappings=[{"group": "ml-team", "workspace": "ml",
                                        "role": EDITOR}])
    oidc = OIDCAuthenticator(config, cp, http=idp)
    app = create_app(WorkspaceManager(str(tmp_path / "ui")),
                     auth=AuthenticatorChain([oidc]), control_plane=cp)
    return TestClient(app, base_url=SERVER), cp


def _transport(client):
    def post_json(url, body):
        assert url.startswith(SERVER)
        r = client.post(url[len(SERVER):], json=body)
        return r.status_code, r.json()

    return post_json


def test_login_writes_a_0600_credentials_file_with_a_working_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    client, cp = _server(tmp_path, FakeDeviceIdP(pending_polls=2))
    prompts = []
    code = login_cli.login(SERVER, post_json=_transport(client),
                           sleep=lambda s: None, say=prompts.append)
    assert code == 0
    assert any("ABCD-EFGH" in p and "/activate" in p for p in prompts)
    path = tmp_path / "home" / ".config" / "vmn-exp" / "credentials"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    token = json.loads(path.read_text())["servers"][SERVER]["token"]
    assert token.startswith("vmnx_")
    r = client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert login_cli.load_token(SERVER) == token
    logins = [e for e in AuditLog(cp).entries() if e["action"] == "login"]
    assert logins and logins[-1]["actor"] == "oidc:u1"


def test_token_carries_the_mapped_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    client, cp = _server(tmp_path, FakeDeviceIdP(pending_polls=0))
    assert login_cli.login(SERVER, post_json=_transport(client),
                           sleep=lambda s: None, say=lambda m: None) == 0
    from vmn_exp.ui.auth.tokens import TokenService

    token = login_cli.load_token(SERVER)
    principal = TokenService(cp).verify(token)
    assert principal.roles == {"ml": EDITOR} and principal.id.startswith("token:")
    assert (tmp_path / "xdg" / "vmn-exp" / "credentials").exists()


def test_unknown_device_code_is_refused(tmp_path):
    client, _ = _server(tmp_path, FakeDeviceIdP())
    r = client.post("/auth/device/token", json={"device_code": "forged"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_login_fails_cleanly_when_the_idp_denies(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    class Denying(FakeDeviceIdP):
        def post_form(self, url, data):
            if url.endswith("/token"):
                return {"error": "access_denied"}
            return super().post_form(url, data)

    client, _ = _server(tmp_path, Denying())
    msgs = []
    code = login_cli.login(SERVER, post_json=_transport(client),
                           sleep=lambda s: None, say=msgs.append)
    assert code == 1 and any("access_denied" in m for m in msgs)
    assert not (tmp_path / "home" / ".config" / "vmn-exp" / "credentials").exists()


def test_login_keeps_other_servers_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    login_cli.save_token("https://other", "vmnx_a_b")
    client, _ = _server(tmp_path, FakeDeviceIdP(pending_polls=0))
    login_cli.login(SERVER, post_json=_transport(client), sleep=lambda s: None,
                    say=lambda m: None)
    assert login_cli.load_token("https://other") == "vmnx_a_b"
    assert login_cli.load_token(SERVER).startswith("vmnx_")


def test_vmn_exp_login_dispatches_to_the_login_command(monkeypatch):
    from vmn_exp.cli import main as main_mod

    seen = []
    monkeypatch.setattr(login_cli, "login", lambda server, **kw: seen.append(server) or 0)
    assert main_mod.main(["login", "--server", SERVER]) == 0
    assert seen == [SERVER]


def test_urllib_http_returns_oauth_error_bodies(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from vmn_exp.ui.auth.oidc_http import UrllibHttp

    def fail(req, timeout):
        body = io.BytesIO(b'{"error": "authorization_pending"}')
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    assert UrllibHttp().post_form(f"{ISSUER}/token", {}) == {"error": "authorization_pending"}


def test_server_app_wires_the_control_plane(tmp_path):
    import argparse

    from vmn_exp.ui.cli import server_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    args = argparse.Namespace(host="127.0.0.1", read_only=False, no_index=False)
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    app = server_app(WorkspaceManager(str(tmp_path / "ui")), None, cp, args)
    assert app.state.control_plane is cp and app.state.audit is not None
