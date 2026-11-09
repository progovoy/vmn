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
local work instead of re-reading storage. A record its version's predicate
picks (it does not read right) is left out, with its run state, and listed
to read again (:mod:`vmn_exp.core.index_reread`): only those runs cost
storage reads. Other records are not copied: the index loads afresh from
storage.
"""
import contextlib
import json
import threading

try:
    import fcntl
except ImportError:  # Windows: only this process's threads take turns
    fcntl = None

from vmn_exp.core import index_reread, index_store_schema, sqlite_files
from vmn_exp.core.index_store_kv import write_puts
from vmn_exp.core.index_store_schema import RECORD_TABLES, RecordsOutdated, mark_derive_pending
from vmn_exp.core.sqlite_conn import connect, write_tx

COPY_CHUNK = 500
LOCK_SUFFIX = ".upgrade"
_LOCKS = {}  # logical path -> the lock this process's upgraders of it take turns under
_LOCKS_LOCK = threading.Lock()


def upgrade(path, connect_file):
    """``(connection, file)`` of *path*'s live database opened through
    *connect_file(file)*, a new generation built first when its records are
    outdated — by one upgrader at a time: one that waited opens what the one
    before it built."""
    with _one_upgrader(path):
        file = sqlite_files.live_path(path)
        try:
            return connect_file(file), file
        except RecordsOutdated as exc:
            return regenerate(path, file, exc.found, connect_file)


@contextlib.contextmanager
def _one_upgrader(path):
    with _LOCKS_LOCK:
        lock = _LOCKS.setdefault(path, threading.Lock())
    with lock:
        if fcntl is None:
            yield
            return
        with open(path + LOCK_SUFFIX, "a") as held:  # closing it unlocks it
            fcntl.flock(held, fcntl.LOCK_EX)
            yield


def regenerate(path, old, found, connect_file):
    """``(connection, file)`` of a new generation of *path*'s database,
    live, built beside its *old* file of records version *found* through
    *connect_file(file)*."""
    fresh = sqlite_files.new_generation(path)
    conn = None
    try:
        conn = connect_file(fresh)
        if found in index_store_schema.COPYABLE_RECORDS:
            _copy_records(old, conn, index_store_schema.COPYABLE_RECORDS[found])
        sqlite_files.flip(path, fresh)
    except BaseException:
        if conn is not None:
            conn.close()
        sqlite_files.remove_if_unused(fresh)
        raise
    return conn, fresh


def _copy_records(old, conn, stale):
    source = connect(old, readonly=True)
    reread = set()  # the (app, key) of the records *stale* picks
    try:
        for table in RECORD_TABLES:  # exp_index first: its picks filter exp_index_state
            _copy_table(source, conn, table, _keeps(table, stale, reread))
        with write_tx(conn):
            mark_derive_pending(conn)
            write_puts(conn, index_reread.puts(conn, reread))
    finally:
        source.close()


def _keeps(table, stale, reread):
    """``keeps(row, columns)`` of *table*: whether the copy keeps it — not a
    record whose fold *stale* (None: none) picks (its key joins *reread*),
    nor the run state of one."""
    if stale is None or table not in ("exp_index", "exp_index_state"):
        return lambda row, columns: True
    if table == "exp_index_state":
        return lambda row, columns: (row[columns["app"]], row[columns["key"]]) not in reread

    def keeps(row, columns):
        data = row[columns["data"]]
        if data is None or not stale(json.loads(data)):
            return True
        reread.add((row[columns["app"]], row[columns["key"]]))
        return False

    return keeps


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _copy_table(source, conn, table, keeps):
    """*table*'s rows *keeps* keeps, the columns both files have, a chunk per
    transaction."""
    ours = set(_columns(conn, table))
    columns = [c for c in _columns(source, table) if c in ours]
    names, marks = ", ".join(columns), ", ".join("?" * len(columns))
    at = {column: i for i, column in enumerate(columns)}
    after = 0
    while True:
        rows = source.execute(
            f"SELECT rowid, {names} FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (after, COPY_CHUNK)).fetchall()
        if not rows:
            return
        kept = [row[1:] for row in rows if keeps(row[1:], at)]
        with write_tx(conn):
            conn.executemany(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({marks})", kept)
        after = rows[-1][0]
