#!/usr/bin/env python3
"""A file of older records (:data:`~vmn_exp.core.index_store_schema.RECORDS_VERSION`)
is never upgraded in place: dropping a live 13 GB file's tables holds its
write lock for minutes. :func:`regenerate` builds a new generation file beside
it (:mod:`vmn_exp.core.sqlite_files`) and flips the pointer to it; the old
file is not written to, and goes once nothing holds it open (the sweep).

Records whose version is in
:data:`~vmn_exp.core.index_store_schema.COPYABLE_RECORDS` still read right:
they are copied over first (:data:`COPY_CHUNK` rows per transaction), every
app then left to re-derive from them (:mod:`vmn_exp.core.index_derive`) —
local work instead of re-reading storage. Other records are not copied: the
index loads afresh from storage.
"""
from vmn_exp.core import index_store_schema, sqlite_files
from vmn_exp.core.index_store_schema import RECORD_TABLES, mark_derive_pending
from vmn_exp.core.sqlite_conn import connect, write_tx

COPY_CHUNK = 500


def regenerate(path, old, found, connect_file):
    """``(connection, file)`` of a new generation of *path*'s database,
    live, built beside its *old* file of records version *found* through
    *connect_file(file)*."""
    fresh = sqlite_files.new_generation(path)
    conn = None
    try:
        conn = connect_file(fresh)
        if found in index_store_schema.COPYABLE_RECORDS:
            _copy_records(old, conn)
        sqlite_files.flip(path, fresh)
    except BaseException:
        if conn is not None:
            conn.close()
        sqlite_files.remove_if_unused(fresh)
        raise
    return conn, fresh


def _copy_records(old, conn):
    source = connect(old, readonly=True)
    try:
        for table in RECORD_TABLES:
            _copy_table(source, conn, table)
        with write_tx(conn):
            mark_derive_pending(conn)
    finally:
        source.close()


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _copy_table(source, conn, table):
    """*table*'s rows, the columns both files have, a chunk per transaction."""
    ours = set(_columns(conn, table))
    columns = [c for c in _columns(source, table) if c in ours]
    names, marks = ", ".join(columns), ", ".join("?" * len(columns))
    after = 0
    while True:
        rows = source.execute(
            f"SELECT rowid, {names} FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (after, COPY_CHUNK)).fetchall()
        if not rows:
            return
        with write_tx(conn):
            conn.executemany(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({marks})",
                             [row[1:] for row in rows])
        after = rows[-1][0]
