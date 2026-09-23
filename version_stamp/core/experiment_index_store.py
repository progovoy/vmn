#!/usr/bin/env python3
"""SQLite persistence for :mod:`version_stamp.core.experiment_index`.

The index is a derived cache: losing it costs one rebuild, never data. So this
store never raises. A database that will not open, is corrupt, or stays locked
is treated as missing — the in-memory index is still correct, just colder next
time. Several processes (the CLI, the SDK, a ``vmn ui`` server) may share one
database: WAL, a busy timeout and one short transaction per refresh.
"""
import json
import logging
import os
import sqlite3

# Bump whenever a record's shape or the fold's semantics change: records
# written by another version are dropped rather than trusted.
SCHEMA_VERSION = "exp-index-1"
_BUSY_TIMEOUT_MS = 5000

_LOGGER = logging.getLogger(__name__)


def _connect(path):
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass  # e.g. a filesystem without shared memory: the default journal works
    conn.execute("CREATE TABLE IF NOT EXISTS exp_index_meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS exp_index ("
        " app TEXT, key TEXT, data TEXT, PRIMARY KEY (app, key))"
    )
    row = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    if not row or row[0] != SCHEMA_VERSION:
        conn.execute("DELETE FROM exp_index")
        conn.execute(
            "INSERT OR REPLACE INTO exp_index_meta (k, v) VALUES ('schema', ?)",
            (SCHEMA_VERSION,),
        )
    conn.commit()
    return conn


def _remove_database(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


class IndexStore:
    """Per-app record rows in one SQLite file; a no-op when *path* is None."""

    def __init__(self, path):
        self._conn = None
        if path:
            self._conn = self._open(path)

    @staticmethod
    def _open(path):
        try:
            return _connect(path)
        except (sqlite3.OperationalError, OSError):
            # Locked by another process, read-only, missing directory: the file
            # may hold other caches too, so it is left alone — just not used.
            _LOGGER.debug("Experiment index %s unavailable", path, exc_info=True)
            return None
        except sqlite3.DatabaseError:
            # Not a database (or a corrupt one): it is only a cache — start over.
            _LOGGER.debug("Rebuilding unreadable experiment index %s", path, exc_info=True)
            _remove_database(path)
        except sqlite3.Error:
            _LOGGER.debug("Experiment index %s unavailable", path, exc_info=True)
            return None
        try:
            return _connect(path)
        except (sqlite3.Error, OSError):
            _LOGGER.debug("Experiment index %s unavailable", path, exc_info=True)
            return None

    def load(self, app_name):
        """``{key: record}`` persisted for *app_name*; ``{}`` when unavailable."""
        if self._conn is None:
            return {}
        try:
            rows = self._conn.execute(
                "SELECT key, data FROM exp_index WHERE app = ?", (app_name,)
            ).fetchall()
            return {key: json.loads(data) for key, data in rows}
        except (sqlite3.Error, ValueError):
            _LOGGER.debug("Could not read the experiment index", exc_info=True)
            return {}

    def save(self, app_name, changed, removed):
        """Persist *changed* records and forget *removed* keys, best effort."""
        if self._conn is None or not (changed or removed):
            return
        try:
            with self._conn:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO exp_index (app, key, data) VALUES (?, ?, ?)",
                    [
                        (app_name, key, json.dumps(record, default=str))
                        for key, record in changed.items()
                    ],
                )
                self._conn.executemany(
                    "DELETE FROM exp_index WHERE app = ? AND key = ?",
                    [(app_name, key) for key in removed],
                )
        except sqlite3.Error:
            # Locked by another process past the timeout, read-only, full disk:
            # the next refresh recomputes whatever did not get persisted.
            _LOGGER.debug("Could not persist the experiment index", exc_info=True)
