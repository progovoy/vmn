#!/usr/bin/env python3
"""Tables of :class:`vmn_exp.core.index_store.SqliteStore`.

``seq`` stamps each row with the scope generation that last wrote it (indexed
with the app, and stored before the JSON so a key scan never walks past it);
``exp_index_gen`` holds a scope's generation and its tombstone ``horizon``
(the newest trimmed tombstone's seq — a follower behind it needs a full load).

A record is stored as its ``head`` (everything but its fold and run state:
the signatures a refresh compares) and its ``data`` (the fold). What readers
read of it is persisted beside it in the same transaction (plan 25 §2): its
lean row in ``exp_rows`` — the columns ``list`` sorts and filters on as real
columns — and its side table values in ``exp_sides``, one row per non-empty
``kind`` (see :mod:`vmn_exp.core.index_lean_store`), and its similar-runs
document in the ``similar_*`` tables (:mod:`vmn_exp.core.similar_fts`).
"""
import sqlite3

from vmn_exp.core import similar_fts
from vmn_exp.core.sqlite_conn import write_tx

# Bump whenever a record's shape, the fold's semantics or these tables change:
# records written by an older version are dropped rather than trusted, and a
# file written by a newer version is left to it.
SCHEMA_VERSION = "exp-index-19"

_TABLES = {
    "exp_index": "app TEXT, key TEXT, seq INTEGER, head TEXT, data TEXT,"
                 " PRIMARY KEY (app, key)",
    "exp_index_state": "app TEXT, key TEXT, seq INTEGER, data TEXT, PRIMARY KEY (app, key)",
    "exp_index_tombstones": "app TEXT, key TEXT, seq INTEGER, ts REAL, PRIMARY KEY (app, key)",
    "exp_index_gen": "app TEXT PRIMARY KEY, gen INTEGER, horizon INTEGER",
    "exp_index_kv": "scope TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT",
    "exp_rows": "app TEXT, key TEXT, verstr TEXT, idx INTEGER, status TEXT, parent TEXT,"
                " root TEXT, timestamp TEXT, name TEXT, archived INTEGER, seq INTEGER,"
                " row TEXT, PRIMARY KEY (app, key)",
    "exp_sides": "app TEXT, key TEXT, kind TEXT, data TEXT, PRIMARY KEY (app, key, kind)",
}
_SEQ_INDEXED = ("exp_index", "exp_index_state", "exp_index_tombstones")
_ROW_INDEXES = {
    "idx": "idx", "status": "status", "parent": "parent", "root": "root",
    "timestamp": "timestamp, key", "verstr": "verstr",
}


class SchemaTooNew(Exception):
    """The file was written by a newer vmn-exp: leave it to that version."""


def _number(version):
    prefix, _, number = (version or "").rpartition("-")
    return int(number) if prefix == "exp-index" and number.isdigit() else None


def is_newer(found, ours=SCHEMA_VERSION):
    """Whether the schema *found* in a file is newer than *ours*."""
    found_n, ours_n = _number(found), _number(ours)
    return found_n is not None and ours_n is not None and found_n > ours_n


def schema_of(conn):
    """The schema version a file's tables were written by; None for a new file."""
    try:
        row = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None  # a new file
        raise
    return row[0] if row else None


def ensure_schema(conn):
    """Create the tables, replacing ones an older schema wrote, all in one
    transaction; raises :class:`SchemaTooNew` for a newer schema's file."""
    if _checked(conn) == SCHEMA_VERSION:
        return
    with write_tx(conn):
        if _checked(conn) != SCHEMA_VERSION:  # another process may have just done it
            _create(conn)


def _checked(conn):
    found = schema_of(conn)
    if is_newer(found):
        raise SchemaTooNew(found)
    return found


def _create(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS exp_index_meta (k TEXT PRIMARY KEY, v TEXT)")
    for table, columns in _TABLES.items():
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"CREATE TABLE {table} ({columns})")
    for table in _SEQ_INDEXED:
        conn.execute(f"CREATE INDEX {table}_seq ON {table} (app, seq)")
    for name, columns in _ROW_INDEXES.items():
        conn.execute(f"CREATE INDEX exp_rows_{name} ON exp_rows (app, {columns})")
    similar_fts.create_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO exp_index_meta (k, v) VALUES ('schema', ?)", (SCHEMA_VERSION,)
    )
