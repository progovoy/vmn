#!/usr/bin/env python3
"""Browser sessions: a random cookie value, stored only as its sha256."""
import hashlib
import secrets
import time
from dataclasses import asdict, replace

from vmn_exp.ui.auth.principal import Principal
from vmn_exp.ui.tenancy import effective_org, org_context

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
        with org_context(principal.org_id or effective_org(0)):
            self.store.put("session", _key(session_id), asdict(principal), expires)
        return session_id

    def principal(self, session_id):
        if not session_id:
            return None
        key = _key(session_id)
        org_id = self.store.credential_org("session", key)
        if org_id is None:
            return None
        with org_context(org_id):
            doc = self.store.get("session", key, now=self.clock())
        return replace(Principal(**doc), org_id=org_id) if doc else None

    def close(self, session_id):
        if session_id:
            key = _key(session_id)
            org_id = self.store.credential_org("session", key)
            if org_id is not None:
                with org_context(org_id):
                    self.store.delete("session", key)
