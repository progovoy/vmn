"""OIDC authorization code + PKCE login against a minimal fake IdP."""
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.oidc import SESSION_COOKIE, OIDCAuthenticator, OIDCConfig
from vmn_exp.ui.auth.principal import EDITOR, VIEWER
from vmn_exp.ui.control_plane import SQLiteControlPlane

ISSUER = "https://idp.example"


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt(claims):
    head = _b64(json.dumps({"alg": "RS256"}).encode())
    return f"{head}.{_b64(json.dumps(claims).encode())}.sig"


class FakeIdP:
    """Discovery + token endpoint; checks client auth, redirect and PKCE."""

    def __init__(self, claims=None, issuer=ISSUER):
        self.issuer = issuer
        self.claims = claims or {"sub": "u1", "name": "Alice", "groups": ["ml-team"]}
        self.codes = {}

    def authorize(self, url):
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert url.startswith(f"{ISSUER}/authorize?")
        assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
        assert "openid" in q["scope"].split()
        code = f"code{len(self.codes)}"
        self.codes[code] = q
        return code, q["state"]

    def get_json(self, url):
        assert url == f"{ISSUER}/.well-known/openid-configuration"
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
        }

    def post_form(self, url, data):
        assert url == f"{ISSUER}/token"
        req = self.codes.pop(data["code"], None)
        if req is None or data["client_secret"] != "shh":
            raise PermissionError("invalid_grant")
        challenge = _b64(hashlib.sha256(data["code_verifier"].encode()).digest())
        if challenge != req["code_challenge"] or data["redirect_uri"] != req["redirect_uri"]:
            raise PermissionError("invalid_grant")
        claims = {"iss": self.issuer, "aud": "vmn-exp", "exp": 4e9, "nonce": req["nonce"]}
        claims.update(self.claims)
        return {"access_token": "at", "id_token": _jwt(claims)}


def _client(tmp_path, idp):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    config = OIDCConfig(
        issuer=ISSUER,
        client_id="vmn-exp",
        client_secret="shh",
        redirect_uri="https://testserver/auth/callback",
        role_mappings=[
            {"group": "ml-team", "workspace": "ml", "role": EDITOR},
            {"group": "everyone", "workspace": "*", "role": VIEWER},
        ],
    )
    store = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    oidc = OIDCAuthenticator(config, store, http=idp)
    app = create_app(WorkspaceManager(str(tmp_path / "ui")), auth=AuthenticatorChain([oidc]))

    @app.get("/api/v1/_whoami")
    def _whoami(request: fastapi.Request):
        p = request.state.principal
        return {"id": p.id, "name": p.name, "roles": p.roles}

    # Ahead of the SPA/API catch-alls create_app registered last.
    app.router.routes.insert(0, app.router.routes.pop())
    return TestClient(app, base_url="https://testserver")


def _login(client, idp):
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    code, state = idp.authorize(r.headers["location"])
    return client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)


def test_login_flow_sets_session_and_principal(tmp_path):
    idp = FakeIdP()
    client = _client(tmp_path, idp)
    assert client.get("/api/v1/_whoami").status_code == 401
    r = _login(client, idp)
    assert r.status_code in (302, 303, 307)
    r = client.get("/api/v1/_whoami")
    assert r.status_code == 200
    assert r.json() == {"id": "oidc:u1", "name": "Alice", "roles": {"ml": EDITOR}}


def test_session_cookie_flags(tmp_path):
    idp = FakeIdP()
    r = _login(_client(tmp_path, idp), idp)
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    lowered = cookie.lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=lax" in lowered
    assert "path=/" in lowered


def test_state_is_single_use_and_checked(tmp_path):
    idp = FakeIdP()
    client = _client(tmp_path, idp)
    r = client.get("/auth/login", follow_redirects=False)
    code, state = idp.authorize(r.headers["location"])
    bad = client.get(f"/auth/callback?code={code}&state=forged", follow_redirects=False)
    assert bad.status_code == 400
    ok = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert ok.status_code in (302, 303, 307)
    again = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert again.status_code == 400


def test_wrong_issuer_or_nonce_rejected(tmp_path):
    idp = FakeIdP(claims={"sub": "u1", "iss": "https://evil.example"})
    client = _client(tmp_path, idp)
    assert _login(client, idp).status_code == 400
    idp2 = FakeIdP(claims={"sub": "u1", "nonce": "replayed"})
    client2 = _client(tmp_path / "b", idp2)
    assert _login(client2, idp2).status_code == 400
    assert client2.get("/api/v1/_whoami").status_code == 401


def test_logout_ends_session(tmp_path):
    idp = FakeIdP()
    client = _client(tmp_path, idp)
    _login(client, idp)
    assert client.get("/api/v1/_whoami").status_code == 200
    stolen = client.cookies.get(SESSION_COOKIE)
    client.post("/auth/logout", headers={"Content-Type": "application/json"}, json={})
    client.cookies.set(SESSION_COOKIE, stolen)
    assert client.get("/api/v1/_whoami").status_code == 401


def test_forged_cookie_rejected(tmp_path):
    client = _client(tmp_path, FakeIdP())
    client.cookies.set(SESSION_COOKIE, "made-up")
    assert client.get("/api/v1/_whoami").status_code == 401


def test_discovery_issuer_mismatch_fails_login_cleanly(tmp_path):
    client = _client(tmp_path, FakeIdP(issuer="https://evil.example"))
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 502
    assert "issuer" in r.json()["detail"]
