#!/usr/bin/env python3
"""OIDC device flow (RFC 8628) for ``vmn-exp login``, run by the server.

The CLI never talks to the IdP: it asks the server to start a device
authorization, shows the user code, and polls the server. The IdP's
device_code stays server-side under an opaque handle. On approval the server
checks the id_token like the browser flow and mints an API token carrying
the user's roles (group mappings resolved at login).
"""
import secrets

from vmn_exp.ui.auth.oidc import OIDCError
from vmn_exp.ui.auth.tokens import TokenService

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
LOGIN_TOKEN_TTL_SEC = 90 * 24 * 3600
PENDING_ERRORS = ("authorization_pending", "slow_down")
_KEY = "device:"


class DeviceFlowError(Exception):
    """An OAuth-style error: ``code`` is ``authorization_pending``, ``invalid_grant``..."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class DeviceFlow:
    def __init__(self, oidc, ttl_sec=LOGIN_TOKEN_TTL_SEC):
        self.oidc = oidc
        self.tokens = TokenService(oidc.store, clock=oidc.clock)
        self.ttl_sec = ttl_sec

    def start(self):
        """What the CLI shows and polls with; ``device_code`` is our handle."""
        endpoint = self.oidc.metadata().get("device_authorization_endpoint")
        if not endpoint:
            raise OIDCError("the identity provider has no device authorization endpoint")
        try:
            grant = self.oidc.http.post_form(endpoint, self._client_form(
                scope=" ".join(self.oidc.config.scopes)))
        except Exception as exc:
            raise OIDCError("device authorization failed") from exc
        if "device_code" not in grant:
            raise OIDCError(f"device authorization failed: {grant.get('error')}")
        handle = secrets.token_urlsafe(32)
        expires_in = int(grant.get("expires_in") or 600)
        self.oidc.store.put("login", _KEY + handle, {"device_code": grant["device_code"]},
                            self.oidc.clock() + expires_in)
        shown = ("user_code", "verification_uri", "verification_uri_complete", "interval")
        return {"device_code": handle, "expires_in": expires_in,
                **{k: grant[k] for k in shown if k in grant}}

    def poll(self, handle):
        """``(plaintext token, record, principal)`` once approved, else raises
        :class:`DeviceFlowError`."""
        key = _KEY + (handle or "")
        pending = self.oidc.store.get("login", key, now=self.oidc.clock())
        if pending is None:
            raise DeviceFlowError("invalid_grant")
        reply = self._exchange(pending["device_code"])
        if reply.get("error") in PENDING_ERRORS:
            raise DeviceFlowError(reply["error"])
        self.oidc.store.delete("login", key)
        if "error" in reply:
            raise DeviceFlowError(reply["error"])
        try:
            principal = self.oidc.principal_for(self.oidc.checked_claims(reply.get("id_token")))
        except OIDCError as exc:
            raise DeviceFlowError("invalid_grant") from exc
        token, record = self.tokens.create(
            f"vmn-exp login ({principal.name})", principal.roles,
            owner=principal.id, ttl_sec=self.ttl_sec)
        return token, record, principal

    def _exchange(self, device_code):
        form = self._client_form(grant_type=DEVICE_GRANT, device_code=device_code)
        try:
            return self.oidc.http.post_form(self.oidc.metadata()["token_endpoint"], form)
        except Exception as exc:
            raise DeviceFlowError("server_error") from exc

    def _client_form(self, **fields):
        form = {"client_id": self.oidc.config.client_id, **fields}
        if self.oidc.config.client_secret:
            form["client_secret"] = self.oidc.config.client_secret
        return form
