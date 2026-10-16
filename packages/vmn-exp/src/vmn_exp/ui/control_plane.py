#!/usr/bin/env python3
"""The server's own state: tokens, sessions, pending logins, workspaces, audit.

:class:`ControlPlaneStore` is the interface; :class:`SQLiteControlPlane` keeps
it in a file under the server data dir, and
:class:`~vmn_exp.ui.control_plane_pg.PostgresControlPlane` in Postgres. Values
are JSON documents keyed by id, so the interface stays small; pages, counts,
scans and sweeps run in SQL. :meth:`ControlPlaneStore.server_key` holds the
server's own secrets (the API token HMAC key), generated on first use.
"""
import json
import os
import secrets
import sqlite3
import threading

CONTROL_PLANE_FILE = "control_plane.sqlite3"
SCAN_BATCH = 1000
SERVER_KEY_BYTES = 32

# Migration 0002_identity (0001 is reserved for the cache tables of plan 11).
_IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS vmn_api_tokens (
    id TEXT PRIMARY KEY, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vmn_sessions (
    id TEXT PRIMARY KEY, doc TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS vmn_login_states (
    id TEXT PRIMARY KEY, doc TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS vmn_sessions_expires ON vmn_sessions (expires_at);
CREATE INDEX IF NOT EXISTS vmn_login_states_expires ON vmn_login_states (expires_at);
"""
# Migration 0003_workspaces: the workspace registry when the server has a DB.
_WORKSPACES_SCHEMA = """
CREATE TABLE IF NOT EXISTS vmn_workspaces (
    id TEXT PRIMARY KEY, doc TEXT NOT NULL
);
"""
# Migration 0003_audit: who did what through the server (plan 11 §6.2).
_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS vmn_audit (
    id TEXT PRIMARY KEY, doc TEXT NOT NULL
);
"""
# Migration 0006: server-wide secrets.
_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS vmn_settings (
    k TEXT PRIMARY KEY, v TEXT NOT NULL
);
"""
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
        """Every doc, oldest first, read *batch* at a time (a generator)."""
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
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.executescript(
            _IDENTITY_SCHEMA + _WORKSPACES_SCHEMA + _AUDIT_SCHEMA + _SETTINGS_SCHEMA)

    @classmethod
    def in_data_dir(cls, data_dir):
        return cls(os.path.join(data_dir, CONTROL_PLANE_FILE))

    def put(self, kind, key, doc, expires_at=None):
        table, cols, args = _TABLES[kind], "id, doc", [key, json.dumps(doc)]
        if kind not in _NON_EXPIRING:
            cols, args = cols + ", expires_at", args + [expires_at or 0]
        marks = ", ".join("?" * len(args))
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})", args)

    def get(self, kind, key, now=None):
        with self._lock:
            return self._get(kind, key, now)

    def pop(self, kind, key, now=None):
        with self._lock:
            doc = self._get(kind, key, now)
            self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id = ?", (key,))
            return doc

    def delete(self, kind, key):
        with self._lock:
            cur = self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id = ?", (key,))
            return cur.rowcount > 0

    def list(self, kind):
        return self._docs(f"SELECT doc FROM {_TABLES[kind]} ORDER BY rowid", ())

    def page(self, kind, offset, limit):
        return self._docs(
            f"SELECT doc FROM {_TABLES[kind]} ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (limit, offset))

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
        with self._lock:
            for kind in EXPIRING:
                self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE expires_at <= ?", (now,))

    def delete_keys_below(self, kind, bound):
        with self._lock:
            self._db.execute(f"DELETE FROM {_TABLES[kind]} WHERE id < ?", (bound,))

    def _load_server_key(self, name, fresh):
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO vmn_settings (k, v) VALUES (?, ?)",
                             (name, fresh))
            return self._db.execute("SELECT v FROM vmn_settings WHERE k = ?", (name,)).fetchone()[0]

    def _docs(self, sql, args):
        with self._lock:
            return [json.loads(doc) for (doc,) in self._db.execute(sql, args).fetchall()]

    def _get(self, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE id = ?"
        args = [key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > ?"
            args.append(now)
        row = self._db.execute(sql, args).fetchone()
        return json.loads(row[0]) if row else None
