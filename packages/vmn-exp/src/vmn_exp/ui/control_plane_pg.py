#!/usr/bin/env python3
""":class:`ControlPlaneStore` on Postgres (tables from migrations 0002_identity, 0003_audit)."""
import threading

from vmn_exp.ui import migrations
from vmn_exp.ui.control_plane import _NON_EXPIRING, _TABLES, ControlPlaneStore


class PostgresControlPlane(ControlPlaneStore):
    def __init__(self, dsn):
        from psycopg.types.json import Jsonb

        self._jsonb = Jsonb
        self._lock = threading.Lock()
        self._db = migrations.connect(dsn)

    def put(self, kind, key, doc, expires_at=None):
        table, cols, args = _TABLES[kind], ["id", "doc"], [key, self._jsonb(doc)]
        if kind not in _NON_EXPIRING:
            cols, args = cols + ["expires_at"], args + [expires_at or 0]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            f" ON CONFLICT (id) DO UPDATE SET {updates}"
        )
        with self._lock:
            self._db.execute(sql, args)

    def get(self, kind, key, now=None):
        with self._lock:
            return self._get(kind, key, now)

    def pop(self, kind, key, now=None):
        with self._lock, self._db.transaction():
            doc = self._get(kind, key, now)
            self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id = %s", (key,))
            return doc

    def delete(self, kind, key):
        with self._lock:
            cur = self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id = %s", (key,))
            return cur.rowcount > 0

    def list(self, kind):
        with self._lock:
            rows = self._db.execute(f"SELECT doc FROM {_TABLES[kind]} ORDER BY created")
            return [doc for (doc,) in rows]

    def _get(self, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE id = %s"
        args = [key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > %s"
            args.append(now)
        row = self._db.execute(sql, args).fetchone()
        return row[0] if row else None
