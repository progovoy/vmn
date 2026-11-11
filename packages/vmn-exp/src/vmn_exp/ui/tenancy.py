#!/usr/bin/env python3
"""Multi tenancy (plan 11 §6.3): orgs, membership and row-level security.

Every control-plane and cache row carries ``org_id``; migration
``0004_tenancy`` defines a policy per table matching it against the session
setting ``app.org_id``. :func:`enable_rls` turns the policies on (``ENABLE`` +
``FORCE``, so the table owner is bound too) for ``tenancy: multi``; a
connection whose transaction never ran :func:`bind_org` then sees no rows. The org
middleware binds the principal's org to each request (``request.state.org_id``
and :func:`current_org`); the Postgres stores bind it per transaction
(:func:`bind_org`), so one shared connection serves every org and no org
outlives its transaction.
"""
import contextlib
import contextvars
from dataclasses import dataclass

SINGLE_TENANT_ORG = 0
RLS_TABLES = (
    "vmn_records", "vmn_run_states", "vmn_tombstones", "vmn_scope_gen", "vmn_kv",
    "vmn_api_tokens", "vmn_sessions", "vmn_login_states", "vmn_workspaces", "vmn_audit",
    "vmn_search_rows",
)
CREDENTIAL_TABLES = ("vmn_api_tokens", "vmn_sessions")


_CURRENT_ORG = contextvars.ContextVar("vmn_org_id", default=None)


def current_org():
    """The org the running request is bound to, or None outside one."""
    return _CURRENT_ORG.get()


@contextlib.contextmanager
def org_context(org_id):
    token = _CURRENT_ORG.set(org_id)
    try:
        yield
    finally:
        _CURRENT_ORG.reset(token)


def effective_org(default):
    """The request's org, else *default* (a store's own, for background work)."""
    org = current_org()
    return default if org is None else org


class DefaultOrg:
    """A store working in the request's org, else its own ``_default_org``."""

    @property
    def _org(self):
        return effective_org(self._default_org)


@dataclass(frozen=True)
class Org:
    id: int
    name: str
    external_id: str


def enable_rls(conn):
    for table in RLS_TABLES:
        conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    _allow_credential_lookup(conn)


def _allow_credential_lookup(conn):
    """Auth runs before a request's org is known: a transaction naming one
    credential id (token id / session hash) in ``app.credential_id`` may read
    that row, in any org, to learn its org."""
    for table in CREDENTIAL_TABLES:
        conn.execute(f"DROP POLICY IF EXISTS vmn_credential_lookup ON {table}")
        conn.execute(
            f"CREATE POLICY vmn_credential_lookup ON {table} FOR SELECT"
            " USING (id = nullif(current_setting('app.credential_id', true), ''))"
        )


def bind_org(conn, org_id):
    """Bind *conn*'s current transaction to *org_id* (``set_config(..., true)``)."""
    conn.execute("SELECT set_config('app.org_id', %s, true)", (str(int(org_id)),))


def create_org(conn, name, random):
    """A new org with a fresh external id (the AssumeRole confused-deputy guard)."""
    external_id = f"vmn-{random.token_hex(16)}"
    (org_id,) = conn.execute(
        "INSERT INTO vmn_orgs (name, external_id) VALUES (%s, %s) RETURNING id",
        (name, external_id),
    ).fetchone()
    return Org(org_id, name, external_id)


def add_member(conn, org_id, principal_id, role):
    conn.execute(
        "INSERT INTO vmn_memberships (org_id, principal, role) VALUES (%s, %s, %s)"
        " ON CONFLICT (org_id, principal) DO UPDATE SET role = EXCLUDED.role",
        (org_id, principal_id, role),
    )


def org_of(conn, principal_id):
    """The org *principal_id* belongs to, or None."""
    row = conn.execute(
        "SELECT org_id FROM vmn_memberships WHERE principal = %s ORDER BY org_id LIMIT 1",
        (principal_id,),
    ).fetchone()
    return row[0] if row else None


class OrgBinding:
    """Plain ASGI (a BaseHTTPMiddleware leaves cyclic garbage per request):
    ``request.state.org_id`` from the principal, and in multi tenancy
    :func:`current_org` for the request; a principal without an org is
    refused (403). ``scope["state"]`` is what ``request.state`` wraps."""

    def __init__(self, app, tenancy):
        self.app = app
        self.tenancy = tenancy

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        principal = state.get("principal")
        org_id = getattr(principal, "org_id", SINGLE_TENANT_ORG)
        if self.tenancy != "multi":
            state["org_id"] = SINGLE_TENANT_ORG
            await self.app(scope, receive, send)
        elif principal is not None and not org_id:
            from fastapi.responses import JSONResponse

            await JSONResponse({"detail": "No organization for this principal"}, 403)(scope, receive, send)
        else:
            state["org_id"] = org_id
            with org_context(org_id):
                await self.app(scope, receive, send)


def install_org_middleware(app, tenancy):
    """Install :class:`OrgBinding` on *app*."""
    app.add_middleware(OrgBinding, tenancy=tenancy)
