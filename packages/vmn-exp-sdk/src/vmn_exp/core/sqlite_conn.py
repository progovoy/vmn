#!/usr/bin/env python3
"""The one SQLite connection policy of vmn-exp's database files (plan 25 §2).

WAL with ``synchronous=NORMAL`` (a commit is durable once checkpointed, never
torn; losing the last commits on power loss only costs a cache a rebuild), a
busy timeout, a bigger page cache, memory-mapped reads, temp tables in
memory. Connections are in autocommit mode (``isolation_level=None``): every
write runs in an explicit :func:`write_tx`, which takes the write lock up
front (``BEGIN IMMEDIATE``), so a read-then-write inside it is never raced.
A connection may be shared by a process's threads: its transactions take
turns under the connection's own lock.

A WAL never keeps its peak size: a checkpoint cuts it back to
:data:`JOURNAL_SIZE_LIMIT`, and :func:`checkpoint` empties it (a server's
connections stay open for its whole life, so no last close ever does).
"""
import contextlib
import os
import sqlite3
import threading

BUSY_TIMEOUT_MS = 5000
CACHE_SIZE = -16384  # KiB (16 MiB), negative as SQLite counts it
MMAP_SIZE = 256 << 20
JOURNAL_SIZE_LIMIT = 64 << 20  # bytes a WAL is cut back to once checkpointed
CHECKPOINT_BUSY_MS = 100  # how long a checkpoint waits for other connections


class _Connection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tx_lock = threading.RLock()


def connect(path, *, readonly=False, busy_timeout_ms=None):
    """A connection to *path* under the policy; *readonly* opens it
    ``mode=ro`` (it must exist). The busy timeout defaults to
    :data:`BUSY_TIMEOUT_MS`."""
    if busy_timeout_ms is None:
        busy_timeout_ms = BUSY_TIMEOUT_MS
    target, uri = (f"file:{path}?mode=ro", True) if readonly else (path, False)
    conn = sqlite3.connect(
        target, uri=uri, timeout=busy_timeout_ms / 1000,
        isolation_level=None, check_same_thread=False, factory=_Connection,
    )
    conn.busy_timeout_ms = int(busy_timeout_ms)
    conn.execute(f"PRAGMA busy_timeout={conn.busy_timeout_ms}")
    conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}")
    if not readonly:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # locked, or no shared memory on this filesystem: keep its journal
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA cache_size={CACHE_SIZE}")
    conn.execute(f"PRAGMA mmap_size={MMAP_SIZE}")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def checkpoint(conn):
    """Copy *conn*'s WAL into its database and truncate it, outside any
    transaction, waiting at most :data:`CHECKPOINT_BUSY_MS` for other
    connections; True when done, False when they kept it busy (try later)."""
    with conn.tx_lock:
        try:
            conn.execute(f"PRAGMA busy_timeout={CHECKPOINT_BUSY_MS}")
            try:
                (busy, _, _) = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            finally:
                conn.execute(f"PRAGMA busy_timeout={conn.busy_timeout_ms}")
        except sqlite3.Error:
            return False
        return not busy


def wal_oversized(file):
    """Whether *file*'s WAL grew past :data:`JOURNAL_SIZE_LIMIT`."""
    try:
        return os.path.getsize(file + "-wal") > JOURNAL_SIZE_LIMIT
    except OSError:
        return False


def in_chunks(values, size=500):
    """``(chunk, marks)`` of *values*, *size* at a time (under SQLite's
    bound-parameter limit); *marks* the chunk's ``?, ?, ...`` placeholders."""
    values = list(values)
    for i in range(0, len(values), size):
        chunk = values[i:i + size]
        yield chunk, ", ".join("?" * len(chunk))


@contextlib.contextmanager
def read_tx(conn):
    """One read transaction on *conn*: its reads see one state of the file."""
    with conn.tx_lock:
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            conn.execute("COMMIT")


@contextlib.contextmanager
def write_tx(conn):
    """One write transaction on *conn*, holding the write lock from its
    start; rolled back when the block raises."""
    with conn.tx_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:  # an I/O error may have rolled it back already
                conn.execute("ROLLBACK")
            raise

