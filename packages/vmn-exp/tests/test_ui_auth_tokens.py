"""API tokens: vmnx_<id>_<secret>, hashed at rest, scoped, revocable, expiring."""
import sqlite3

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.ui.auth.principal import EDITOR, VIEWER
from vmn_exp.ui.auth.tokens import ApiTokenAuthenticator, TokenService
from vmn_exp.ui.control_plane import SQLiteControlPlane


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def svc(tmp_path):
    clock = _Clock()
    path = tmp_path / "cp.sqlite3"
    return TokenService(SQLiteControlPlane(str(path)), clock=clock), clock, path


def test_create_returns_prefixed_secret_and_verifies(svc):
    tokens, _, _ = svc
    secret, record = tokens.create("ci", {"ml": EDITOR}, owner="alice")
    assert secret.startswith(f"vmnx_{record.id}_")
    p = tokens.verify(secret)
    assert p.id == f"token:{record.id}"
    assert p.role_in("ml") == EDITOR
    assert p.role_in("other") is None


def test_only_a_hash_is_stored(svc):
    tokens, _, path = svc
    secret, _ = tokens.create("ci", {"ml": VIEWER})
    dump = "\n".join(sqlite3.connect(str(path)).iterdump())
    assert secret.split("_", 2)[2] not in dump
    assert "scrypt$" in dump or "pbkdf2_sha256$" in dump


def test_wrong_secret_and_garbage_rejected(svc):
    tokens, _, _ = svc
    secret, record = tokens.create("ci", {"ml": VIEWER})
    assert tokens.verify(secret[:-1] + ("A" if secret[-1] != "A" else "B")) is None
    assert tokens.verify(f"vmnx_{record.id}") is None
    assert tokens.verify("vmnx_unknown_secret") is None
    assert tokens.verify("") is None
    assert tokens.verify(None) is None


def test_revoke(svc):
    tokens, _, _ = svc
    secret, record = tokens.create("ci", {"ml": VIEWER})
    assert tokens.revoke(record.id) is True
    assert tokens.verify(secret) is None
    assert tokens.revoke("nope") is False
    assert [t.revoked for t in tokens.list()] == [True]


def test_expiry(svc):
    tokens, clock, _ = svc
    secret, _ = tokens.create("ci", {"ml": VIEWER}, ttl_sec=60)
    clock.now += 59
    assert tokens.verify(secret) is not None
    clock.now += 2
    assert tokens.verify(secret) is None


def test_rejects_unknown_role(svc):
    tokens, _, _ = svc
    with pytest.raises(ValueError):
        tokens.create("ci", {"ml": "root"})


def test_tokens_persist_across_store_instances(svc):
    tokens, clock, path = svc
    secret, _ = tokens.create("ci", {"ml": VIEWER})
    again = TokenService(SQLiteControlPlane(str(path)), clock=clock)
    assert again.verify(secret) is not None


def test_api_token_authenticates_requests(tmp_path, svc):
    from vmn_exp.ui.auth import AuthenticatorChain
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    tokens, _, _ = svc
    secret, _ = tokens.create("ci", {"ml": VIEWER})
    chain = AuthenticatorChain([ApiTokenAuthenticator(tokens)])
    client = TestClient(create_app(WorkspaceManager(str(tmp_path / "ui")), auth=chain))
    assert client.get("/api/v1/workspaces").status_code == 401
    r = client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200
