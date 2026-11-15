"""Browser sessions: keyed by the cookie's hash, closable per principal, roles never frozen."""
import hashlib

import pytest

pytest.importorskip("fastapi")

from vmn_exp.ui.auth.principal import ADMIN, Principal
from vmn_exp.ui.auth.sessions import SessionService
from vmn_exp.ui.control_plane import SQLiteControlPlane
from vmn_exp.core.real_io import RealRandom


class _Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def cp(tmp_path):
    return SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))


def _sessions(cp, clock, **kw):
    return SessionService(cp, clock=clock, **kw, random=RealRandom())


def test_close_principal_closes_only_that_principals_sessions(cp):
    sessions = _sessions(cp, _Clock())
    alice = Principal("oidc:alice", "Alice", groups=("ml",))
    bob = Principal("oidc:bob", "Bob", groups=("ml",))
    a1, a2, b1 = sessions.open(alice), sessions.open(alice), sessions.open(bob)
    assert sessions.close_principal("oidc:alice") == 2
    assert sessions.principal(a1) is None and sessions.principal(a2) is None
    assert sessions.principal(b1).id == "oidc:bob"


def test_session_ttl_from_config(cp):
    clock = _Clock()
    sessions = _sessions(cp, clock, ttl_sec=60)
    sid = sessions.open(Principal("oidc:a", "A"))
    clock.now += 59
    assert sessions.principal(sid) is not None
    clock.now += 2
    assert sessions.principal(sid) is None


def test_session_key_is_stored_and_not_passed_to_the_principal(cp):
    sessions = _sessions(cp, _Clock())
    sid = sessions.open(Principal("oidc:a", "A"))
    key = hashlib.sha256(sid.encode()).hexdigest()
    assert [d["session_key"] for d in cp.list("session")] == [key]
    principal = sessions.principal(sid)
    assert principal.id == "oidc:a" and not hasattr(principal, "session_key")


def test_close_principal_leaves_a_session_stored_without_its_key(cp):
    old = {"id": "oidc:a", "name": "A", "roles": {}, "groups": [], "org_id": 0}
    cp.put("session", "old-key", old, expires_at=2_000_000.0)
    assert _sessions(cp, _Clock()).close_principal("oidc:a") == 0
    assert cp.get("session", "old-key") is not None


def test_stored_session_roles_are_ignored(cp):
    sid = "cookie-value"
    key = hashlib.sha256(sid.encode()).hexdigest()
    old = {"id": "oidc:a", "name": "A", "roles": {"*": ADMIN}, "groups": ["ml"], "org_id": 0}
    cp.put("session", key, old, expires_at=2_000_000.0)
    principal = _sessions(cp, _Clock()).principal(sid)
    assert principal.roles == {} and tuple(principal.groups) == ("ml",)
