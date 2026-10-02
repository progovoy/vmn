#!/usr/bin/env python3
"""Browser sessions: a random cookie value, stored only as its sha256."""
import hashlib
import secrets
import time
from dataclasses import asdict

from vmn_exp.ui.auth.principal import Principal

SESSION_TTL_SEC = 12 * 3600


def _key(session_id):
    return hashlib.sha256(session_id.encode()).hexdigest()


class SessionService:
    def __init__(self, store, clock=time.time, ttl_sec=SESSION_TTL_SEC):
        self.store = store
        self.clock = clock
        self.ttl_sec = ttl_sec

    def open(self, principal):
        """A new session id (the cookie value) for *principal*."""
        session_id = secrets.token_urlsafe(32)
        expires = self.clock() + self.ttl_sec
        self.store.put("session", _key(session_id), asdict(principal), expires)
        return session_id

    def principal(self, session_id):
        if not session_id:
            return None
        doc = self.store.get("session", _key(session_id), now=self.clock())
        return Principal(**doc) if doc else None

    def close(self, session_id):
        if session_id:
            self.store.delete("session", _key(session_id))
