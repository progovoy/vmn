#!/usr/bin/env python3
""":class:`ControlPlaneStore` on Postgres (tables from migrations 0002_identity, 0003_audit, 0004_tenancy).

Every call is one transaction on a connection of the DSN's pool
(:mod:`vmn_exp.ui.pg_pool`), bound to the request's org
(:func:`~vmn_exp.ui.tenancy.current_org`), else the store's *org_id*.
"""
import contextlib

from vmn_exp.ui import pg_pool
from vmn_exp.ui.control_plane import _NON_EXPIRING, _TABLES, ControlPlaneStore
from vmn_exp.ui.tenancy import bind_org, effective_org, enable_rls


class PostgresControlPlane(ControlPlaneStore):
    def __init__(self, dsn, org_id=0):
        from psycopg.types.json import Jsonb

        self._jsonb = Jsonb
        self._default_org = org_id
        self._dsn = dsn

    @property
    def _org(self):
        return effective_org(self._default_org)

    @contextlib.contextmanager
    def _tx(self, org_bound=True):
        with pg_pool.pool(self._dsn).connection() as conn, conn.transaction():
            if org_bound:
                bind_org(conn, self._org)
            yield conn

    def enable_rls(self):
        """Turn the tenancy row-level security policies on (``tenancy: multi``)."""
        with pg_pool.pool(self._dsn).connection() as conn:
            enable_rls(conn)

    def put(self, kind, key, doc, expires_at=None):
        table, cols = _TABLES[kind], ["org_id", "id", "doc"]
        args = [self._org, key, self._jsonb(doc)]
        if kind not in _NON_EXPIRING:
            cols, args = cols + ["expires_at"], args + [expires_at or 0]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[2:])
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            f" ON CONFLICT (org_id, id) DO UPDATE SET {updates}"
        )
        with self._tx() as db:
            db.execute(sql, args)

    def get(self, kind, key, now=None):
        with self._tx() as db:
            return self._get(db, kind, key, now)

    def pop(self, kind, key, now=None):
        with self._tx() as db:
            doc = self._get(db, kind, key, now)
            db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s", (self._org, key))
            return doc

    def delete(self, kind, key):
        with self._tx() as db:
            cur = db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s", (self._org, key))
            return cur.rowcount > 0

    def list(self, kind):
        with self._tx() as db:
            rows = db.execute(
                f"SELECT doc FROM {_TABLES[kind]} WHERE org_id = %s ORDER BY created", (self._org,)
            )
            return [doc for (doc,) in rows]

    def credential_org(self, kind, key):
        # tenancy.enable_rls's vmn_credential_lookup policy lets this one id through in any org.
        with self._tx(org_bound=False) as db:
            db.execute("SELECT set_config('app.credential_id', %s, true)", (key,))
            row = db.execute(
                f"SELECT org_id FROM {_TABLES[kind]} WHERE id = %s ORDER BY org_id LIMIT 1", (key,)
            ).fetchone()
        return row[0] if row else None

    def _get(self, db, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s"
        args = [self._org, key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > %s"
            args.append(now)
        row = db.execute(sql, args).fetchone()
        return row[0] if row else None
