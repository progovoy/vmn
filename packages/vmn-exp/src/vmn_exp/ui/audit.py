#!/usr/bin/env python3
"""The audit log (plan 11 §6.2): control-plane table ``vmn_audit``.

Every request to a mutating API route (any route whose declared role is above
``viewer``) leaves one entry, refused ones included, as do logins. Entries
live in the control plane (backed up, never part of the disposable cache).
An entry's id starts with its zero-padded microsecond timestamp
(:func:`audit_key`), so ids sort by time and retention deletes by id range
(:mod:`~vmn_exp.ui.control_plane_sweep`). Pages and counts run in SQL; the
export streams.
"""
import json
import secrets
import time

from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from vmn_exp.ui.auth.authz import route_role
from vmn_exp.ui.auth.principal import VIEWER

READ_METHODS = ("GET", "HEAD", "OPTIONS")


def audit_key(ts):
    """The id prefix of entries recorded at *ts*; every earlier entry's id sorts below it."""
    return f"{int(ts * 1e6):020d}"


class AuditLog:
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock

    def record(self, actor, action, actor_name="", **fields):
        ts = self.clock()
        entry_id = f"{audit_key(ts)}-{secrets.token_hex(4)}"
        entry = {"id": entry_id, "ts": ts, "actor": actor, "actor_name": actor_name,
                 "action": action, **fields}
        self.store.put("audit", entry_id, entry)
        return entry

    def record_principal(self, principal, action, **fields):
        if principal is None:
            return self.record("anonymous", action, **fields)
        return self.record(principal.id, action, actor_name=principal.name, **fields)

    def entries(self):
        """All entries, oldest first."""
        return self.store.list("audit")

    def page(self, offset=0, limit=100):
        """Newest first."""
        return self.store.page("audit", offset, limit)

    def count(self):
        return self.store.count("audit")

    def export_lines(self):
        """Every entry as a JSON line, oldest first, read in batches."""
        entries = self.store.scan("audit")  # called here, so it captures the request's org
        return (json.dumps(entry) + "\n" for entry in entries)


def audited_route(method, route):
    if method in READ_METHODS or not isinstance(route, APIRoute):
        return False
    return route_role(route) not in (None, VIEWER)


def install_audit_middleware(app):
    """Record mutating requests into ``app.state.audit`` (when it is set).

    Install it before the authenticating middleware, so it runs inside it
    and sees ``request.state.principal``."""

    @app.middleware("http")
    async def _audit(request, call_next):
        response = await call_next(request)
        audit = getattr(app.state, "audit", None)
        route = request.scope.get("route")
        if audit is not None and audited_route(request.method, route):
            await run_in_threadpool(
                audit.record_principal,
                getattr(request.state, "principal", None),
                f"{request.method} {route.path}",
                path=request.url.path,
                workspace=request.scope.get("path_params", {}).get("ws_name"),
                status=response.status_code,
            )
        return response
