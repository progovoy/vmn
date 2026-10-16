#!/usr/bin/env python3
"""SQLite persistence for :mod:`vmn_exp.core.index`.

The index is a derived cache: losing it costs one rebuild, never data. So this
store never raises. A database that will not open or stays locked is treated
as missing for now (retried later, :mod:`vmn_exp.core.index_store_conn`); a
corrupt one is rebuilt beside it; a failed save answers False so the caller
keeps its records dirty. Several processes (the CLI, the SDK, a ``vmn-exp ui``
server) may share one database: the :mod:`vmn_exp.core.sqlite_conn` policy and
one short ``BEGIN IMMEDIATE`` transaction per refresh.

A record's run state lives in its own table: a heartbeat rewrites one small
row, never the record's folded log. Its lean row and side table values are
written beside it (:mod:`vmn_exp.core.index_lean_store`): warm starts and
point reads decode no record (:mod:`vmn_exp.core.index_store_reads`).
Each save bumps the scope generation (see
:mod:`vmn_exp.core.cache_store`); removals leave tombstones for
:meth:`SqliteStore.load_since`, trimmed after :data:`TOMBSTONE_TTL_SEC`.
"""
import json
import logging
import sqlite3
import time

from vmn_exp.core.cache_store import FULL_LOAD, CacheStore  # noqa: F401
from vmn_exp.core.index_lazy import STATE_KEYS as _STATE_KEYS
from vmn_exp.core.index_lean_store import write_lean
from vmn_exp.core.index_store_conn import StoreConnection
from vmn_exp.core.index_store_kv import KeyValues
from vmn_exp.core.index_store_reads import LeanReads
from vmn_exp.core.index_store_schema import SCHEMA_VERSION, ensure_schema  # noqa: F401
from vmn_exp.core.similar_filing import file_records as file_similar
from vmn_exp.core.sqlite_conn import connect, in_chunks, write_tx

_BUSY_TIMEOUT_MS = 5000
TOMBSTONE_TTL_SEC = 600
_now = time.time

_LOGGER = logging.getLogger(__name__)


def _connect(path):
    conn = connect(path, busy_timeout_ms=_BUSY_TIMEOUT_MS)
    try:
        ensure_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


class SqliteStore(LeanReads, KeyValues):
    """A :class:`CacheStore` in one SQLite file; a no-op when *path* is None."""

    def __init__(self, path):
        self._db = StoreConnection(path or None, _connect)
        self._db.get()

    @property
    def path(self):
        """The database's logical path; None for a no-op store."""
        return self._db.path

    def connection(self):
        """``(live connection, the file it holds)``, or None while unavailable."""
        conn = self._db.get()
        return None if conn is None else (conn, self._db.file)

    @property
    def _conn(self):
        return self._db.conn

    def close(self):
        self._db.close()

    def load(self, app_name):
        """``{key: record}`` persisted for *app_name*, each with its
        ``rs_sig``/``run_state``; ``{}`` when unavailable."""
        return self._read(lambda: self._records(app_name), {})

    def load_raw(self, app_name):
        """:meth:`load`'s rows undecoded, for :func:`decode_records`:
        ``([(key, head JSON, fold JSON)], [(key, run state JSON)])``."""
        return self._read(lambda: self._raw(app_name), ([], []))

    def _raw(self, app_name):
        records = self._conn.execute(
            "SELECT key, head, data FROM exp_index WHERE app = ?", (app_name,)
        ).fetchall()
        return records, self._select("exp_index_state", app_name)

    def _records(self, app_name):
        return decode_records(*self._raw(app_name))

    def _read(self, query, default):
        if self._db.get() is None:
            return default
        try:
            return query()
        except sqlite3.Error as exc:
            self._db.on_error(exc)  # corrupt (e.g. replaced since opened): recovers
            return default
        except ValueError:
            _LOGGER.debug("Could not decode the experiment index", exc_info=True)
            return default

    def count(self, app_name):
        """How many records are persisted for *app_name*, without reading
        them; 0 when unavailable."""
        return self._read(lambda: self._conn.execute(
            "SELECT COUNT(*) FROM exp_index WHERE app = ?", (app_name,)
        ).fetchone()[0], 0)

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
        if generation < horizon or generation > gen:
            # Past the tombstones kept, or ahead of a rebuilt file: reload all.
            return self._records(app_name), FULL_LOAD, gen
        keys = sorted({
            key
            for table in ("exp_index", "exp_index_state")
            for (key,) in self._conn.execute(
                f"SELECT key FROM {table} WHERE app = ? AND seq > ?",
                (app_name, generation),
            )
        })
        removed = {
            key for (key,) in self._conn.execute(
                "SELECT key FROM exp_index_tombstones WHERE app = ? AND seq > ?",
                (app_name, generation),
            )
        }
        changed = decode_records(
            self._keyed("exp_index", "head, data", app_name, keys),
            self._keyed("exp_index_state", "data", app_name, keys),
        ) if keys else {}
        return changed, removed, gen

    def _keyed(self, table, columns, app_name, keys):
        """``(key, *columns)`` of *keys*' rows in *table*, a chunk of keys per query."""
        rows = []
        for chunk, marks in in_chunks(keys):
            rows += self._conn.execute(
                f"SELECT key, {columns} FROM {table} WHERE app = ? AND key IN ({marks})",
                (app_name, *chunk),
            ).fetchall()
        return rows

    def _select(self, table, app_name):
        return self._conn.execute(
            f"SELECT key, data FROM {table} WHERE app = ?", (app_name,)
        ).fetchall()

    def save(self, app_name, changed, removed, states=None):
        """Persist *changed* records and the run state of the *states* records
        (both ``{key: record}``), forget *removed* keys. A record's
        ``rs_sig``/``run_state`` are stored only through *states*. True when
        persisted (or nothing to persist), False when the caller should try
        again later; never raises."""
        states = states or {}
        if self._db.path is None or not (changed or removed or states):
            return True
        conn = self._db.get()
        if conn is None:
            return False
        try:
            with write_tx(conn):
                seq = self._bump_generation(app_name)
                self._upsert_records(app_name, seq, changed)
                self._upsert_states(app_name, seq, states)
                self._forget(app_name, seq, removed)
                write_lean(conn, app_name, seq, changed, removed, states)
                file_similar(conn, app_name, changed, removed, states)
                conn.executemany(
                    "DELETE FROM exp_index_tombstones WHERE app = ? AND key = ?",
                    [(app_name, key) for key in changed],
                )
                self._trim_tombstones(app_name)
        except sqlite3.Error as exc:  # locked past the timeout, read-only, full disk
            self._db.on_error(exc, "Could not persist the experiment index {file}"
                                   " ({exc}); the next refresh retries")
            return False
        return True

    def _bump_generation(self, app_name):
        (gen,) = self._conn.execute(
            "INSERT INTO exp_index_gen (app, gen, horizon) VALUES (?, 1, 0)"
            " ON CONFLICT (app) DO UPDATE SET gen = gen + 1 RETURNING gen",
            (app_name,),
        ).fetchone()
        return gen

    def _upsert_records(self, app_name, seq, records):
        self._conn.executemany(
            "INSERT OR REPLACE INTO exp_index (app, key, seq, head, data)"
            " VALUES (?, ?, ?, ?, ?)",
            [(app_name, key, seq, *_encoded(record)) for key, record in records.items()],
        )

    def _upsert_states(self, app_name, seq, records):
        self._conn.executemany(
            "INSERT OR REPLACE INTO exp_index_state (app, key, seq, data) VALUES (?, ?, ?, ?)",
            [
                (app_name, key, seq, json.dumps(_state_of(record), default=str))
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


IndexStore = SqliteStore


def decode_records(rows, states):
    """``{key: record}`` of :meth:`SqliteStore.load_raw`'s rows."""
    records = {key: _decoded(head, data) for key, head, data in rows}
    for key, data in states:
        if key in records:
            records[key].update(json.loads(data))
    return records


_NO_STATE = dict.fromkeys(_STATE_KEYS)


def _state_of(record):
    return {k: record.get(k) for k in _STATE_KEYS}


def _without_state(record):
    return {k: v for k, v in record.items() if k not in _STATE_KEYS}


def _encoded(record):
    """``(head JSON, fold JSON or None)`` of *record* without its run state."""
    head = {k: v for k, v in _without_state(record).items() if k != "fold"}
    return json.dumps(head, default=str), (
        json.dumps(record["fold"], default=str) if "fold" in record else None)


def _decoded(head, data):
    record = {**_NO_STATE, **json.loads(head)}
    return record if data is None else dict(record, fold=json.loads(data))


