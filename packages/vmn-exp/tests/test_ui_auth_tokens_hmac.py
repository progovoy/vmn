"""API token secrets are HMAC-SHA256 under the control plane's server key
(plan 25 §2): no KDF on the request path."""
import hashlib
import time
from dataclasses import asdict

import pytest

from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.auth.tokens import TokenService
from vmn_exp.ui.control_plane import ControlPlaneStore, SQLiteControlPlane


class _DictStore(ControlPlaneStore):
    """In memory, so a timing measures the token check, not a database."""

    def __init__(self):
        self.docs = {}
        self.keys = {}

    def put(self, kind, key, doc, expires_at=None):
        self.docs[(kind, key)] = doc

    def get(self, kind, key, now=None):
        return self.docs.get((kind, key))

    def list(self, kind):
        return [d for (k, _), d in self.docs.items() if k == kind]

    def server_key(self, name):
        return self.keys.setdefault(name, hashlib.sha256(name.encode()).digest())


def _no_kdf(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a KDF ran")

    monkeypatch.setattr(hashlib, "scrypt", refuse, raising=False)
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", refuse)


def test_round_trip_runs_no_kdf(tmp_path, monkeypatch):
    _no_kdf(monkeypatch)
    tokens = TokenService(SQLiteControlPlane(str(tmp_path / "cp.sqlite3")))
    secret, record = tokens.create("ci", {"ml": VIEWER})
    assert record.secret_hash.startswith("hmac-sha256$")
    assert tokens.verify(secret).id == f"token:{record.id}"


def test_a_token_from_another_server_key_fails(tmp_path):
    ours = SQLiteControlPlane(str(tmp_path / "a.sqlite3"))
    theirs = SQLiteControlPlane(str(tmp_path / "b.sqlite3"))
    secret, record = TokenService(theirs).create("ci", {"ml": VIEWER})
    ours.put("token", record.id, asdict(record))
    assert TokenService(ours).verify(secret) is None
    assert TokenService(theirs).verify(secret) is not None


def test_ten_thousand_verifications_are_fast():
    tokens = TokenService(_DictStore())
    secret, _ = tokens.create("ci", {"ml": VIEWER})
    start = time.perf_counter()
    for _ in range(10_000):
        assert tokens.verify(secret) is not None
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize("stored", ["", "hmac-sha256$", "scrypt$1,2,3$x$y", "garbage"])
def test_a_malformed_stored_hash_never_matches(stored):
    store = _DictStore()
    tokens = TokenService(store)
    secret, record = tokens.create("ci", {"ml": VIEWER})
    store.put("token", record.id, {**asdict(record), "secret_hash": stored})
    assert tokens.verify(secret) is None
