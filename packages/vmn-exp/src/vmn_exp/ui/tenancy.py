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
import secrets
from dataclasses import dataclass

SINGLE_TENANT_ORG = 0
RLS_TABLES = (
    "vmn_records", "vmn_run_states", "vmn_tombstones", "vmn_scope_gen", "vmn_kv",
    "vmn_api_tokens", "vmn_sessions", "vmn_login_states", "vmn_workspaces", "vmn_audit",
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


def create_org(conn, name):
    """A new org with a fresh external id (the AssumeRole confused-deputy guard)."""
    external_id = f"vmn-{secrets.token_hex(16)}"
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


def install_org_middleware(app, tenancy):
    """Set ``request.state.org_id`` from the principal; in multi tenancy a
    principal without an org is refused (403)."""

    @app.middleware("http")
    async def bind_org(request, call_next):
        principal = getattr(request.state, "principal", None)
        org_id = getattr(principal, "org_id", SINGLE_TENANT_ORG)
        if tenancy == "multi" and principal is not None and not org_id:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "No organization for this principal"}, 403)
        if tenancy != "multi":
            request.state.org_id = SINGLE_TENANT_ORG
            return await call_next(request)
        request.state.org_id = org_id
        with org_context(org_id):
            return await call_next(request)
