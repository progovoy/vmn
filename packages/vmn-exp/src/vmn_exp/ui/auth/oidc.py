#!/usr/bin/env python3
"""OIDC login for browsers: authorization code + PKCE (S256) via discovery.

The id_token is read from the token endpoint's direct TLS response, so per
OIDC Core 3.1.3.7 its issuer, audience, expiry and nonce are checked but its
signature is not (no JWT library needed). The resulting principal lives in a
server-side session; the browser holds only an opaque ``HttpOnly``,
``SameSite=Lax``, ``Secure`` cookie. CSRF stays covered by ``RequestGuard``.
"""
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from vmn_exp.ui.auth.oidc_http import UrllibHttp
from vmn_exp.ui.auth.principal import Principal, check_roles, stronger
from vmn_exp.ui.auth.sessions import SessionService

SESSION_COOKIE = "vmn_session"
LOGIN_STATE_TTL_SEC = 600
DISCOVERY_PATH = "/.well-known/openid-configuration"


class OIDCError(Exception):
    pass


@dataclass
class OIDCConfig:
    issuer: str
    client_id: str
    redirect_uri: str
    client_secret: str = None
    scopes: tuple = ("openid", "profile", "email")
    groups_claim: str = "groups"
    role_mappings: list = field(default_factory=list)  # {group, workspace, role}


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (AttributeError, IndexError, ValueError) as exc:
        raise OIDCError("malformed id_token") from exc


def roles_for_groups(groups, mappings):
    roles = {}
    for m in mappings:
        if m["group"] in groups:
            roles[m["workspace"]] = stronger(roles.get(m["workspace"]), m["role"])
    return check_roles(roles)


class OIDCAuthenticator:
    def __init__(self, config, store, http=None, clock=time.time):
        self.config = config
        self.store = store
        self.http = http or UrllibHttp()
        self.clock = clock
        self.sessions = SessionService(store, clock=clock)
        self._metadata = None

    def authenticate(self, request):
        return self.sessions.principal(request.cookies.get(SESSION_COOKIE))

    def metadata(self):
        if self._metadata is None:
            try:
                meta = self.http.get_json(self.config.issuer.rstrip("/") + DISCOVERY_PATH)
            except Exception as exc:
                raise OIDCError("discovery failed") from exc
            if meta.get("issuer") != self.config.issuer:
                raise OIDCError("discovery issuer mismatch")
            self._metadata = meta
        return self._metadata

    def login_url(self):
        """The IdP authorize URL; its state/nonce/verifier are kept server-side."""
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        verifier, challenge = pkce_pair()
        expires = self.clock() + LOGIN_STATE_TTL_SEC
        self.store.put("login", state, {"nonce": nonce, "verifier": verifier}, expires)
        query = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.metadata()['authorization_endpoint']}?{urlencode(query)}"

    def complete(self, code, state):
        """Exchange *code*; returns a new session id. Raises :class:`OIDCError`."""
        pending = self.store.pop("login", state or "", now=self.clock())
        if pending is None or not code:
            raise OIDCError("unknown or expired login state")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": pending["verifier"],
        }
        if self.config.client_secret:
            form["client_secret"] = self.config.client_secret
        try:
            tokens = self.http.post_form(self.metadata()["token_endpoint"], form)
        except Exception as exc:
            raise OIDCError("token exchange failed") from exc
        claims = self.checked_claims(tokens.get("id_token"), pending["nonce"])
        return self.sessions.open(self.principal_for(claims))

    def checked_claims(self, id_token, nonce=None):
        """*id_token*'s claims; *nonce* is checked unless ``None`` (device flow)."""
        claims = jwt_claims(id_token)
        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if claims.get("iss") != self.config.issuer or self.config.client_id not in auds:
            raise OIDCError("id_token issuer/audience mismatch")
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= self.clock():
            raise OIDCError("id_token expired")
        nonce_ok = nonce is None or claims.get("nonce") == nonce
        if not nonce_ok or not claims.get("sub"):
            raise OIDCError("id_token nonce mismatch")
        return claims

    def principal_for(self, claims):
        groups = claims.get(self.config.groups_claim) or []
        name = claims.get("name") or claims.get("email") or claims["sub"]
        roles = roles_for_groups(groups, self.config.role_mappings)
        return Principal(f"oidc:{claims['sub']}", name, roles, tuple(groups))

    def router(self):
        from vmn_exp.ui.auth.oidc_routes import oidc_router

        return oidc_router(self)
