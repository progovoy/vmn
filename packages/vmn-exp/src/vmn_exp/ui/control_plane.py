#!/usr/bin/env python3
"""The server's own state (identity today): tokens, sessions, pending logins.

:class:`ControlPlaneStore` is the interface; :class:`SQLiteControlPlane` keeps
it in a file under the server data dir (a Postgres implementation comes with
the central server). Values are JSON documents keyed by id, so the interface
stays small.
"""
import json
import os
import sqlite3
import threading

CONTROL_PLANE_FILE = "control_plane.sqlite3"

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


class SQLiteControlPlane(ControlPlaneStore):
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.executescript(_IDENTITY_SCHEMA + _WORKSPACES_SCHEMA + _AUDIT_SCHEMA)

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
