#!/usr/bin/env python3
"""The server's own state: tokens, sessions, pending logins, workspaces, audit.

:class:`ControlPlaneStore` is the interface; :class:`SQLiteControlPlane` keeps
it in a file under the server data dir, opened under the shared SQLite
connection policy (:mod:`vmn_exp.core.sqlite_conn`); :mod:`control_plane_pg`
keeps it in Postgres. Values are JSON documents keyed by id, so the interface
stays small; pages, counts, scans and sweeps run in SQL.
:meth:`ControlPlaneStore.server_key` holds the server's own secrets (the API
token HMAC key), generated on first use.
"""
import json
import os
import secrets
import threading

from vmn_exp.core import sqlite_conn
from vmn_exp.core.sqlite_conn import write_tx

CONTROL_PLANE_FILE = "control_plane.sqlite3"
SCAN_BATCH = 1000
SERVER_KEY_BYTES = 32

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
    # The expiry sweep's indexes, server-wide secrets, and HMAC tokens
    # (scrypt-hashed ones can't verify any more).
    "0006_control_plane_queries.sql": (
        "CREATE INDEX IF NOT EXISTS vmn_sessions_expires ON vmn_sessions (expires_at)",
        "CREATE INDEX IF NOT EXISTS vmn_login_states_expires ON vmn_login_states (expires_at)",
        "CREATE TABLE IF NOT EXISTS vmn_settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
        "DELETE FROM vmn_api_tokens",
    ),
}
_TABLES = {"token": "vmn_api_tokens", "session": "vmn_sessions", "login": "vmn_login_states",
           "workspace": "vmn_workspaces", "audit": "vmn_audit"}
_NON_EXPIRING = ("token", "workspace", "audit")
EXPIRING = tuple(kind for kind in _TABLES if kind not in _NON_EXPIRING)


def new_server_key():
    return secrets.token_hex(SERVER_KEY_BYTES)


def keyset_scan(fetch, batch):
    """Every doc of *fetch(last)*'s ``(position, doc)`` batches, in order."""
    last = 0
    while True:
        rows = fetch(last)
        for _, doc in rows:
            yield doc
        if len(rows) < batch:
            return
        last = rows[-1][0]


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

    def page(self, kind, offset, limit):
        """Up to *limit* docs, newest first, after skipping *offset*."""
        raise NotImplementedError

    def count(self, kind):
        raise NotImplementedError

    def scan(self, kind, batch=SCAN_BATCH):
        """Every doc, oldest first, read *batch* at a time (an iterator)."""
        raise NotImplementedError

    def sweep_expired(self, now):
        """Delete the sessions and login states expired at *now*."""
        raise NotImplementedError

    def delete_keys_below(self, kind, bound):
        """Delete the docs whose key sorts below *bound*."""
        raise NotImplementedError

    def server_key(self, name):
        """The server's secret *name* (32 bytes), generated on first use and
        read once per store."""
        keys = self.__dict__.setdefault("_server_keys", {})
        if name not in keys:
            keys[name] = bytes.fromhex(self._load_server_key(name, new_server_key()))
        return keys[name]

    def _load_server_key(self, name, fresh):
        """The stored hex value of *name*, storing *fresh* when there is none."""
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

    def page(self, kind, offset, limit):
        sql = f"SELECT doc FROM {_TABLES[kind]} ORDER BY rowid DESC LIMIT ? OFFSET ?"
        with self._lock:
            return [json.loads(doc) for (doc,) in self._db.execute(sql, (limit, offset))]

    def count(self, kind):
        with self._lock:
            return self._db.execute(f"SELECT count(*) FROM {_TABLES[kind]}").fetchone()[0]

    def scan(self, kind, batch=SCAN_BATCH):
        sql = f"SELECT rowid, doc FROM {_TABLES[kind]} WHERE rowid > ? ORDER BY rowid LIMIT ?"

        def fetch(last):
            with self._lock:
                return [(n, json.loads(doc)) for n, doc in self._db.execute(sql, (last, batch))]

        return keyset_scan(fetch, batch)

    def sweep_expired(self, now):
        with self._lock, write_tx(self._db) as db:
            for kind in EXPIRING:
                db.execute(f"DELETE FROM {_TABLES[kind]} WHERE expires_at <= ?", (now,))

    def delete_keys_below(self, kind, bound):
        with self._lock, write_tx(self._db) as db:
            db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id < ?", (bound,))

    def _load_server_key(self, name, fresh):
        with self._lock, write_tx(self._db) as db:
            db.execute("INSERT OR IGNORE INTO vmn_settings (k, v) VALUES (?, ?)", (name, fresh))
            return db.execute("SELECT v FROM vmn_settings WHERE k = ?", (name,)).fetchone()[0]

    def _get(self, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE id = ?"
        args = [key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > ?"
            args.append(now)
        row = self._db.execute(sql, args).fetchone()
        return json.loads(row[0]) if row else None
