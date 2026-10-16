#!/usr/bin/env python3
"""API tokens for scripts calling the server: ``vmnx_<id>_<secret>``.

Only ``hmac-sha256$<hex>`` of the secret is stored, keyed by the server's
``token_hmac`` key (:meth:`~vmn_exp.ui.control_plane.ControlPlaneStore.server_key`):
the secrets are 256 random bits, so a slow KDF would add nothing but cost per
request, and a leaked table can't be checked without the key. The id locates
the record. Tokens carry roles per workspace, an optional expiry, and are
revoked by id.
"""
import hashlib
import hmac
import secrets
import time
from dataclasses import asdict, dataclass

from vmn_exp.ui.auth.principal import Principal, check_roles
from vmn_exp.ui.tenancy import org_context

PREFIX = "vmnx"
SCHEME = "hmac-sha256"
KEY_NAME = "token_hmac"


@dataclass(frozen=True)
class TokenRecord:
    id: str
    name: str
    roles: dict
    owner: str
    created_at: float
    expires_at: float
    revoked: bool
    secret_hash: str


def hash_secret(secret, key):
    """``hmac-sha256$<hex digest>`` of *secret* under *key*."""
    return f"{SCHEME}${hmac.new(key, secret.encode(), hashlib.sha256).hexdigest()}"


def secret_matches(secret, stored, key):
    return hmac.compare_digest(hash_secret(secret, key), stored)


def parse_token(token):
    """``(id, secret)`` from ``vmnx_<id>_<secret>``, else ``None``."""
    parts = (token or "").split("_", 2)
    if len(parts) != 3 or parts[0] != PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


class TokenService:
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock

    def create(self, name, roles, owner="", ttl_sec=None):
        """``(plaintext, record)``; the plaintext is shown once, never stored."""
        token_id, secret = secrets.token_hex(8), secrets.token_urlsafe(32)
        now = self.clock()
        record = TokenRecord(
            id=token_id, name=name, roles=check_roles(roles), owner=owner,
            created_at=now, expires_at=now + ttl_sec if ttl_sec else 0,
            revoked=False, secret_hash=hash_secret(secret, self._key()),
        )
        self.store.put("token", token_id, asdict(record))
        return f"{PREFIX}_{token_id}_{secret}", record

    def verify(self, token):
        """The token's principal, or ``None`` if unknown/wrong/revoked/expired."""
        parsed = parse_token(token)
        if parsed is None:
            return None
        org_id = self.store.credential_org("token", parsed[0])
        if org_id is None:
            return None
        with org_context(org_id):
            record = self._get(parsed[0])
        if record is None or record.revoked:
            return None
        if not secret_matches(parsed[1], record.secret_hash, self._key()):
            return None
        if record.expires_at and self.clock() >= record.expires_at:
            return None
        return Principal(f"token:{record.id}", record.name, dict(record.roles), org_id=org_id)

    def revoke(self, token_id):
        record = self._get(token_id)
        if record is None:
            return False
        self.store.put("token", token_id, {**asdict(record), "revoked": True})
        return True

    def list(self):
        return [TokenRecord(**doc) for doc in self.store.list("token")]

    def _key(self):
        return self.store.server_key(KEY_NAME)

    def _get(self, token_id):
        doc = self.store.get("token", token_id)
        return TokenRecord(**doc) if doc else None


class ApiTokenAuthenticator:
    def __init__(self, tokens):
        self.tokens = tokens

    def authenticate(self, request):
        scheme, _, token = (request.headers.get("Authorization") or "").partition(" ")
        if scheme != "Bearer" or not token.startswith(PREFIX + "_"):
            return None
        return self.tokens.verify(token)
