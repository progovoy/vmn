#!/usr/bin/env python3
"""The server's own state (identity today): tokens, sessions, pending logins.

:class:`ControlPlaneStore` is the interface; :class:`SQLiteControlPlane` keeps
it in a file under the server data dir, opened under the shared SQLite
connection policy (:mod:`vmn_exp.core.sqlite_conn`); :mod:`control_plane_pg`
keeps it in Postgres. Values are JSON documents keyed by id, so the interface
stays small.
"""
import json
import os
import threading

from vmn_exp.core import sqlite_conn
from vmn_exp.core.sqlite_conn import write_tx

CONTROL_PLANE_FILE = "control_plane.sqlite3"

# The SQLite steps of the Postgres migrations (ui/migrations/NNNN_name.sql),
# recorded under the same names in vmn_schema_migrations. 0001_cache,
# 0004_tenancy and 0005_search are Postgres-only (one org, no shared cache).
_STEPS = {
    "0002_identity.sql": (
        "CREATE TABLE IF NOT EXISTS vmn_api_tokens (id TEXT PRIMARY KEY, doc TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS vmn_sessions"
        " (id TEXT PRIMARY KEY, doc TEXT NOT NULL, expires_at REAL NOT NULL)",
        "CREATE TABLE IF NOT EXISTS vmn_login_states"
        " (id TEXT PRIMARY KEY, doc TEXT NOT NULL, expires_at REAL NOT NULL)",
    ),
    # The workspace registry when the server has a DB, and who did what
    # through the server (plan 11 §6.2).
    "0003_audit.sql": (
        "CREATE TABLE IF NOT EXISTS vmn_workspaces (id TEXT PRIMARY KEY, doc TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS vmn_audit (id TEXT PRIMARY KEY, doc TEXT NOT NULL)",
    ),
}
_TABLES = {"token": "vmn_api_tokens", "session": "vmn_sessions", "login": "vmn_login_states",
           "workspace": "vmn_workspaces", "audit": "vmn_audit"}
_NON_EXPIRING = ("token", "workspace", "audit")


class ControlPlaneStore:
    """Key/document storage per kind (``token``, ``session``, ``login``, ``workspace``, ``audit``)."""

    def put(self, kind, key, doc, expires_at=None):
        raise NotImplementedError

    def get(self, kind, key, now=None):
        """The doc, or ``None`` if absent or expired at *now*."""
        raise NotImplementedError

    def pop(self, kind, key, now=None):
        """Get and delete in one step (single-use values)."""
        raise NotImplementedError

    def delete(self, kind, key):
        raise NotImplementedError

    def list(self, kind):
        raise NotImplementedError

    def credential_org(self, kind, key):
        """The org a ``token``/``session`` *key* belongs to, looked up before
        any org is bound; ``None`` if unknown. One org without tenancy."""
        return 0 if self.get(kind, key) is not None else None


class SQLiteControlPlane(ControlPlaneStore):
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite_conn.connect(path)
        self._migrate()

    def _migrate(self):
        """Apply the steps not yet recorded, under the write lock, so
        processes opening the file together apply each one once."""
        with write_tx(self._db) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS vmn_schema_migrations"
                " (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            done = {name for (name,) in db.execute("SELECT name FROM vmn_schema_migrations")}
            for name in sorted(set(_STEPS) - done):
                for statement in _STEPS[name]:
                    db.execute(statement)
                db.execute("INSERT INTO vmn_schema_migrations (name) VALUES (?)", (name,))

    @classmethod
    def in_data_dir(cls, data_dir):
        return cls(os.path.join(data_dir, CONTROL_PLANE_FILE))

    def put(self, kind, key, doc, expires_at=None):
        table, cols, args = _TABLES[kind], "id, doc", [key, json.dumps(doc)]
        if kind not in _NON_EXPIRING:
            cols, args = cols + ", expires_at", args + [expires_at or 0]
        marks = ", ".join("?" * len(args))
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols.split(", ")[1:])
        # An upsert keeps the row (and its rowid, the listing order).
        sql = f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT (id) DO UPDATE SET {updates}"
        with self._lock, write_tx(self._db) as db:
            db.execute(sql, args)

    def get(self, kind, key, now=None):
        with self._lock:
            return self._get(kind, key, now)

    def pop(self, kind, key, now=None):
        # One statement: of processes popping the same key, one gets the row.
        expiry = "0" if kind in _NON_EXPIRING else "expires_at"
        sql = f"DELETE FROM {_TABLES[kind]} WHERE id = ? RETURNING doc, {expiry}"
        with self._lock, write_tx(self._db) as db:
            row = db.execute(sql, (key,)).fetchone()
        if row is None or (now is not None and kind not in _NON_EXPIRING and row[1] <= now):
            return None
        return json.loads(row[0])

    def delete(self, kind, key):
        with self._lock, write_tx(self._db) as db:
            cur = db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id = ?", (key,))
            return cur.rowcount > 0

    def list(self, kind):
        with self._lock:
            rows = self._db.execute(f"SELECT doc FROM {_TABLES[kind]} ORDER BY rowid")
            return [json.loads(doc) for (doc,) in rows]

    def _get(self, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE id = ?"
        args = [key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > ?"
            args.append(now)
        row = self._db.execute(sql, args).fetchone()
        return json.loads(row[0]) if row else None
