#!/usr/bin/env python3
"""SQLite persistence for :mod:`vmn_exp.core.index`.

The index is a derived cache: losing it costs one rebuild, never data. So this
store never raises. A database that will not open, is corrupt, or stays locked
is treated as missing — the in-memory index is still correct, just colder next
time. Several processes (the CLI, the SDK, a ``vmn-exp ui`` server) may share one
database: WAL, a busy timeout and one short transaction per refresh.

A record's run state lives in its own table: a heartbeat rewrites one small
row, never the record's folded log. Each save bumps the scope generation (see
:mod:`vmn_exp.core.cache_store`); removals leave tombstones for
:meth:`SqliteStore.load_since`, trimmed after :data:`TOMBSTONE_TTL_SEC`.
"""
import json
import logging
import os
import sqlite3
import time

from vmn_exp.core.cache_store import FULL_LOAD, CacheStore  # noqa: F401
from vmn_exp.core.index_store_schema import SCHEMA_VERSION, ensure_schema  # noqa: F401

_BUSY_TIMEOUT_MS = 5000
TOMBSTONE_TTL_SEC = 600
_now = time.time

_LOGGER = logging.getLogger(__name__)


def _connect(path):
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass  # e.g. a filesystem without shared memory: the default journal works
    ensure_schema(conn)
    return conn


def _remove_database(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


class SqliteStore:
    """A :class:`CacheStore` in one SQLite file; a no-op when *path* is None."""

    def __init__(self, path):
        self._conn = None
        self._path = None
        if path:
            self._path = path
            self._conn = self._open(self._path)

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

    def _reset(self):
        """Discard a corrupt connection and reconnect via _open (which deletes
        the unreadable file and rebuilds a fresh one)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._path:
            self._conn = self._open(self._path)

    def load(self, app_name):
        """``{key: record}`` persisted for *app_name*, each with its
        ``rs_sig``/``run_state``; ``{}`` when unavailable."""
        return self._read(lambda: self._records(app_name), {})

    def _records(self, app_name, keys=None):
        records = {
            key: dict(_state_of({}), **json.loads(data))
            for key, data in self._select("exp_index", app_name)
            if keys is None or key in keys
        }
        for key, data in self._select("exp_index_state", app_name):
            if key in records:
                records[key].update(json.loads(data))
        return records

    def _read(self, query, default):
        if self._conn is None:
            return default
        try:
            return query()
        except (sqlite3.Error, ValueError) as exc:
            if type(exc) is sqlite3.DatabaseError:
                # File corruption detected on a read (e.g. file was replaced
                # after the connection was opened).  Reset so future calls work.
                _LOGGER.debug(
                    "Corrupt experiment index on read %s; resetting",
                    self._path, exc_info=True,
                )
                self._reset()
            else:
                _LOGGER.debug("Could not read the experiment index", exc_info=True)
            return default

    def generation(self, app_name):
        """The scope's generation; 0 before its first save or when unavailable."""
        return self._read(lambda: self._gen_row(app_name)[0], 0)

    def _gen_row(self, app_name):
        row = self._conn.execute(
            "SELECT gen, horizon FROM exp_index_gen WHERE app = ?", (app_name,)
        ).fetchone()
        return row or (0, 0)

    def load_since(self, app_name, generation):
        """``(changed, removed, new_gen)`` since *generation*; *removed* is
        :data:`FULL_LOAD` (and *changed* everything) past the tombstone horizon."""
        return self._read(lambda: self._delta(app_name, generation), ({}, set(), 0))

    def _delta(self, app_name, generation):
        gen, horizon = self._gen_row(app_name)
        if generation < horizon:
            return self._records(app_name), FULL_LOAD, gen
        keys = {
            key
            for table in ("exp_index", "exp_index_state")
            for (key,) in self._conn.execute(
                f"SELECT key FROM {table} WHERE app = ? AND seq > ?",
                (app_name, generation),
            )
        }
        removed = {
            key for (key,) in self._conn.execute(
                "SELECT key FROM exp_index_tombstones WHERE app = ? AND seq > ?",
                (app_name, generation),
            )
        }
        changed = self._records(app_name, keys) if keys else {}
        return changed, removed, gen

    def _select(self, table, app_name):
        return self._conn.execute(
            f"SELECT key, data FROM {table} WHERE app = ?", (app_name,)
        ).fetchall()

    def save(self, app_name, changed, removed, states=None):
        """Persist *changed* records and the run state of the *states* records
        (both ``{key: record}``), forget *removed* keys — best effort. A
        record's ``rs_sig``/``run_state`` are stored only through *states*."""
        states = states or {}
        if self._conn is None or not (changed or removed or states):
            return
        try:
            with self._conn:
                seq = self._bump_generation(app_name)
                self._upsert("exp_index", app_name, seq, changed, _without_state)
                self._upsert("exp_index_state", app_name, seq, states, _state_of)
                self._forget(app_name, seq, removed)
                self._conn.executemany(
                    "DELETE FROM exp_index_tombstones WHERE app = ? AND key = ?",
                    [(app_name, key) for key in changed],
                )
                self._trim_tombstones(app_name)
        except sqlite3.Error:
            # Locked by another process past the timeout, read-only, full disk:
            # the next refresh recomputes whatever did not get persisted.
            _LOGGER.debug("Could not persist the experiment index", exc_info=True)

    def _bump_generation(self, app_name):
        gen, horizon = self._gen_row(app_name)
        self._conn.execute(
            "INSERT OR REPLACE INTO exp_index_gen (app, gen, horizon) VALUES (?, ?, ?)",
            (app_name, gen + 1, horizon),
        )
        return gen + 1

    def _upsert(self, table, app_name, seq, records, shape):
        self._conn.executemany(
            f"INSERT OR REPLACE INTO {table} (app, key, data, seq) VALUES (?, ?, ?, ?)",
            [
                (app_name, key, json.dumps(shape(record), default=str), seq)
                for key, record in records.items()
            ],
        )

    def _forget(self, app_name, seq, removed):
        gone = [(app_name, key) for key in removed]
        for table in ("exp_index", "exp_index_state"):
            self._conn.executemany(f"DELETE FROM {table} WHERE app = ? AND key = ?", gone)
        self._conn.executemany(
            "INSERT OR REPLACE INTO exp_index_tombstones (app, key, seq, ts)"
            " VALUES (?, ?, ?, ?)",
            [(app_name, key, seq, _now()) for key in removed],
        )

    def _trim_tombstones(self, app_name):
        cutoff = (app_name, _now() - TOMBSTONE_TTL_SEC)
        (newest,) = self._conn.execute(
            "SELECT MAX(seq) FROM exp_index_tombstones WHERE app = ? AND ts < ?", cutoff
        ).fetchone()
        if newest is None:
            return
        self._conn.execute(
            "DELETE FROM exp_index_tombstones WHERE app = ? AND ts < ?", cutoff
        )
        self._conn.execute(
            "UPDATE exp_index_gen SET horizon = MAX(horizon, ?) WHERE app = ?",
            (newest, app_name),
        )

    def kv_get(self, scope, fingerprint):
        """The payload under *scope* when stored with *fingerprint*, else None."""
        row = self._read(
            lambda: self._conn.execute(
                "SELECT fingerprint, payload FROM exp_index_kv WHERE scope = ?", (scope,)
            ).fetchone(),
            None,
        )
        if row and row[0] == fingerprint:
            return json.loads(row[1])
        return None

    def kv_put(self, scope, fingerprint, payload):
        """Store *payload* under *scope* — best effort."""
        if self._conn is None:
            return
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO exp_index_kv (scope, fingerprint, payload)"
                    " VALUES (?, ?, ?)",
                    (scope, fingerprint, json.dumps(payload)),
                )
        except sqlite3.Error:
            _LOGGER.debug("Could not persist a cache entry", exc_info=True)


IndexStore = SqliteStore


_STATE_KEYS = ("rs_sig", "run_state")


def _state_of(record):
    return {k: record.get(k) for k in _STATE_KEYS}


def _without_state(record):
    return {k: v for k, v in record.items() if k not in _STATE_KEYS}
