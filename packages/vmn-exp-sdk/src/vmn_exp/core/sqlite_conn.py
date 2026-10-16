#!/usr/bin/env python3
"""The one SQLite connection policy of vmn-exp's database files (plan 25 §2).

WAL with ``synchronous=NORMAL`` (a commit is durable once checkpointed, never
torn; losing the last commits on power loss only costs a cache a rebuild), a
busy timeout, a bigger page cache, memory-mapped reads, temp tables in
memory. Connections are in autocommit mode (``isolation_level=None``): every
write runs in an explicit :func:`write_tx`, which takes the write lock up
front (``BEGIN IMMEDIATE``), so a read-then-write inside it is never raced.
"""
import contextlib
import sqlite3

BUSY_TIMEOUT_MS = 5000
CACHE_SIZE = -16384  # KiB (16 MiB), negative as SQLite counts it
MMAP_SIZE = 256 << 20


def connect(path, *, readonly=False, busy_timeout_ms=BUSY_TIMEOUT_MS):
    """A connection to *path* under the policy; *readonly* opens it
    ``mode=ro`` (it must exist)."""
    target, uri = (f"file:{path}?mode=ro", True) if readonly else (path, False)
    conn = sqlite3.connect(
        target, uri=uri, timeout=busy_timeout_ms / 1000,
        isolation_level=None, check_same_thread=False,
    )
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
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


@contextlib.contextmanager
def write_tx(conn):
    """One write transaction on *conn*, holding the write lock from its
    start; rolled back when the block raises."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:  # an I/O error may have rolled it back already
            conn.execute("ROLLBACK")
        raise
