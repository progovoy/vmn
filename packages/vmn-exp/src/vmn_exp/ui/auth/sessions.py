#!/usr/bin/env python3
"""Browser sessions: a random cookie value, stored only as its sha256.

The document keeps that hash as ``session_key`` (a listing returns documents
without their keys), so :meth:`SessionService.close_principal` can close one
principal's sessions. Roles are never read back from a session: they are
derived from its groups on each request (:mod:`authz`).
"""
import hashlib
import secrets
from dataclasses import asdict, replace

from vmn_exp.ui.auth.principal import Principal
from vmn_exp.ui.tenancy import effective_org, org_context

SESSION_TTL_SEC = 12 * 3600


def _key(session_id):
    return hashlib.sha256(session_id.encode()).hexdigest()


class SessionService:
    def __init__(self, store, clock, ttl_sec=SESSION_TTL_SEC):
        self.store = store
        self.clock = clock
        self.ttl_sec = ttl_sec

    def open(self, principal):
        """A new session id (the cookie value) for *principal*."""
        session_id = secrets.token_urlsafe(32)
        now = self.clock()
        self.store.sweep_expired(now)
        expires = now + self.ttl_sec
        with org_context(principal.org_id or effective_org(0)):
            key = _key(session_id)
            self.store.put("session", key, {**asdict(principal), "session_key": key}, expires)
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
        if not doc:
            return None
        doc.pop("session_key", None)
        return replace(Principal(**doc), roles={}, org_id=org_id)

    def close(self, session_id):
        if session_id:
            key = _key(session_id)
            org_id = self.store.credential_org("session", key)
            if org_id is not None:
                with org_context(org_id):
                    self.store.delete("session", key)

    def close_principal(self, principal_id):
        """Close every session of *principal_id* in the current org; how many.
        A session stored before ``session_key`` existed cannot be found."""
        keys = [doc["session_key"] for doc in self.store.list("session")
                if doc.get("id") == principal_id and doc.get("session_key")]
        return sum(1 for key in keys if self.store.delete("session", key))
