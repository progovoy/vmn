#!/usr/bin/env python3
"""API tokens for scripts calling the server: ``vmnx_<id>_<secret>``.

Only a salted hash of the secret is stored: stdlib ``hashlib.scrypt`` (no new
dependency; argon2 is not installed), PBKDF2-SHA256 where the Python build
lacks scrypt. The id locates the record. Tokens carry roles per workspace,
an optional expiry, and are revoked by id.
"""
import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import asdict, dataclass

from vmn_exp.ui.auth.principal import Principal, check_roles
from vmn_exp.ui.tenancy import org_context

PREFIX = "vmnx"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
# Secrets are 256 random bits, so the KDF only guards a leaked table.
PBKDF2_ITERATIONS = 100_000


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


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode()


def _derive(scheme, params, secret, salt):
    if scheme == "scrypt":
        n, r, p = (int(x) for x in params.split(","))
        return hashlib.scrypt(secret.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    if scheme == "pbkdf2_sha256":
        return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, int(params))
    raise ValueError(f"unknown hash scheme {scheme}")


def _default_scheme():
    # hashlib.scrypt needs OpenSSL 1.1+; some builds (macOS LibreSSL) lack it.
    if hasattr(hashlib, "scrypt"):
        return "scrypt", "{n},{r},{p}".format(**_SCRYPT)
    return "pbkdf2_sha256", str(PBKDF2_ITERATIONS)


def hash_secret(secret):
    """``<scheme>$<params>$<salt>$<digest>`` of *secret*."""
    scheme, params = _default_scheme()
    salt = secrets.token_bytes(16)
    digest = _derive(scheme, params, secret, salt)
    return f"{scheme}${params}${_b64(salt)}${_b64(digest)}"


def secret_matches(secret, stored):
    try:
        scheme, params, salt, digest = stored.split("$")
        given = _derive(scheme, params, secret, base64.urlsafe_b64decode(salt))
    except ValueError:
        return False
    return hmac.compare_digest(_b64(given), digest)


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
            revoked=False, secret_hash=hash_secret(secret),
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
        if record is None or record.revoked or not secret_matches(parsed[1], record.secret_hash):
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
