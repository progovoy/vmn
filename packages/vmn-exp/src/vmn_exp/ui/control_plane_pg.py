#!/usr/bin/env python3
""":class:`ControlPlaneStore` on Postgres (tables from migrations 0002_identity, 0003_audit, 0004_tenancy).

Every call is one transaction bound to the request's org
(:func:`~vmn_exp.ui.tenancy.current_org`), else the store's *org_id*.
"""
import contextlib
import threading

from vmn_exp.ui import migrations
from vmn_exp.ui.control_plane import _NON_EXPIRING, _TABLES, ControlPlaneStore
from vmn_exp.ui.tenancy import bind_org, effective_org, enable_rls


class PostgresControlPlane(ControlPlaneStore):
    def __init__(self, dsn, org_id=0):
        from psycopg.types.json import Jsonb

        self._jsonb = Jsonb
        self._lock = threading.Lock()
        self._default_org = org_id
        self._db = migrations.connect(dsn)

    @property
    def _org(self):
        return effective_org(self._default_org)

    @contextlib.contextmanager
    def _tx(self):
        with self._lock, self._db.transaction():
            bind_org(self._db, self._org)
            yield

    def enable_rls(self):
        """Turn the tenancy row-level security policies on (``tenancy: multi``)."""
        with self._lock:
            enable_rls(self._db)

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
        with self._tx():
            self._db.execute(sql, args)

    def get(self, kind, key, now=None):
        with self._tx():
            return self._get(kind, key, now)

    def pop(self, kind, key, now=None):
        with self._tx():
            doc = self._get(kind, key, now)
            self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s", (self._org, key))
            return doc

    def delete(self, kind, key):
        with self._tx():
            cur = self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s", (self._org, key))
            return cur.rowcount > 0

    def list(self, kind):
        with self._tx():
            rows = self._db.execute(
                f"SELECT doc FROM {_TABLES[kind]} WHERE org_id = %s ORDER BY created", (self._org,)
            )
            return [doc for (doc,) in rows]

    def _get(self, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s"
        args = [self._org, key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > %s"
            args.append(now)
        row = self._db.execute(sql, args).fetchone()
        return row[0] if row else None
