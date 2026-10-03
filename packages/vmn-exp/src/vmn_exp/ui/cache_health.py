#!/usr/bin/env python3
"""Is the server's cache still the one it built? (plan 11 §4.6)

Checked every tick, cheaply: a ``problem()`` of None means healthy, else a
short reason that starts a background rebuild. SQLite: the file was deleted,
replaced (another inode), is unreadable, or carries another
``SCHEMA_VERSION``. Postgres: the cache tables were truncated (a scope's
generation went backwards, or the ``vmn_cache_meta`` row is gone) or hold
another schema version. An unreachable database is not a problem: the store
reconnects on its own.
"""
import os
import sqlite3

from vmn_exp.core.index_store_schema import SCHEMA_VERSION


def _identity(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _schema_of(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


class SqliteHealth:
    def __init__(self, path):
        self.path = path
        self.rearm()

    def rearm(self):
        """Accept the file now at the path (a rebuild swapped it in)."""
        self._identity = _identity(self.path)

    def problem(self):
        identity = _identity(self.path)
        if identity is None:
            return "missing"
        if identity != self._identity:
            return "replaced"
        try:
            schema = _schema_of(self.path)
        except sqlite3.OperationalError as exc:
            return None if "locked" in str(exc) else "corrupt"
        except sqlite3.DatabaseError:
            return "corrupt"
        return None if schema == SCHEMA_VERSION else "schema"


class PgHealth:
    def __init__(self, store):
        self._store = store
        self._seen = {}  # scope -> the highest generation observed

    def observe(self, scope):
        """Watch *scope*'s generation for a regression."""
        self._seen[scope] = max(self._seen.get(scope, 0), self._store.generation(scope))

    def rearm(self):
        self._seen = dict.fromkeys(self._seen, 0)
        for scope in list(self._seen):
            self.observe(scope)

    def problem(self):
        version = self._store.cache_version()
        if version is None:
            return None  # unreachable: nothing to judge
        if version == "":
            return "truncated"
        if version != SCHEMA_VERSION:
            return "schema"
        for scope, seen in self._seen.items():
            if self._store.generation(scope) < seen:
                return "truncated"
            self.observe(scope)
        return None

    def floor(self):
        """A generation past every one a follower may hold."""
        return max(self._seen.values(), default=0)
