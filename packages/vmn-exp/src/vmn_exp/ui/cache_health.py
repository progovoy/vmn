#!/usr/bin/env python3
"""Is the server's cache still the one it built? (plan 11 §4.6)

Checked every tick, cheaply: a ``problem()`` of None means healthy, else a
short reason that starts a background rebuild. SQLite: the live file (the
one its pointer names, :mod:`vmn_exp.core.sqlite_files`) was deleted,
replaced (another inode, or another process flipped the pointer), is
unreadable, or holds older records (``RECORDS_VERSION``; a newer version
belongs to a newer server sharing the file: rebuilding over it would
ping-pong). Older derived tables (``DERIVED_VERSION``) are ``derived``: no
rebuild, a re-derive from the file's own records (see
:mod:`vmn_exp.core.index_store_schema`).
Postgres: the cache tables were truncated (a scope's generation went
backwards, or the ``vmn_cache_meta`` row is gone) or hold another records
version (it caches records only: a derived-only upgrade leaves it be). An unreachable database is not a problem: the store
reconnects on its own.
"""
import os
import sqlite3

from vmn_exp.core.index_store_schema import (
    DERIVED,
    RECORDS_VERSION,
    RecordsOutdated,
    SchemaTooNew,
    records_version,
    upgrade_of,
)
from vmn_exp.core.sqlite_conn import connect
from vmn_exp.core.sqlite_files import live_path


def _identity(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


_SQLITE_HEADER = b"SQLite format 3\x00"


def _has_sqlite_header(path):
    """Whether the file still starts as SQLite's: with page 1 in an
    uncheckpointed WAL a read would not notice the file itself is gone bad."""
    try:
        with open(path, "rb") as f:
            return f.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def _upgrade_of(path):
    conn = connect(path, readonly=True)
    try:
        return upgrade_of(conn)
    finally:
        conn.close()


class SqliteHealth:
    def __init__(self, path):
        self.path = path
        self.rearm()

    def rearm(self):
        """Accept the file now live (a rebuild swapped it in)."""
        self._identity = _identity(live_path(self.path))

    def problem(self):
        file = live_path(self.path)
        identity = _identity(file)
        if self._identity is None:  # not created yet when armed: the first one counts
            self._identity = identity
            if identity is None:
                return None
        if identity is None:
            return "missing"
        if identity != self._identity:
            return "replaced"
        if not _has_sqlite_header(file):
            return "corrupt"
        try:
            upgrade = _upgrade_of(file)
        except SchemaTooNew:
            return None
        except RecordsOutdated:
            return "schema"
        except sqlite3.OperationalError as exc:
            return None if "locked" in str(exc) else "corrupt"
        except sqlite3.DatabaseError:
            return "corrupt"
        if upgrade is None or upgrade == DERIVED:
            return upgrade
        return "schema"  # a new file: no tables


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
        meta = self._store.cache_meta()
        if meta is None:
            return None  # unreachable: nothing to judge
        if "schema_version" not in meta:
            return "truncated"
        if records_version(meta["schema_version"], meta.get("records")) != RECORDS_VERSION:
            return "schema"
        for scope, seen in self._seen.items():
            if self._store.generation(scope) < seen:
                return "truncated"
            self.observe(scope)
        return None

    def floor(self):
        """A generation past every one a follower may hold."""
        return max(self._seen.values(), default=0)
