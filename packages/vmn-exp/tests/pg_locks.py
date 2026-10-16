"""Helpers for Postgres reconnect tests: block a table, find and kill the
backends waiting on it."""
import contextlib
import time

import psycopg

_WAITING = (
    "SELECT pid FROM pg_stat_activity"
    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


def until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def waiting_pids(dsn):
    with psycopg.connect(dsn, autocommit=True) as conn:
        return [pid for (pid,) in conn.execute(_WAITING)]


def wait_for_waiters(dsn, count, timeout=10.0):
    """The pids once *count* backends wait on a lock."""
    pids = []

    def enough():
        pids[:] = waiting_pids(dsn)
        return len(pids) >= count

    until(enough, timeout)
    return pids


def terminate(dsn, *pids):
    with psycopg.connect(dsn, autocommit=True) as conn:
        for pid in pids:
            conn.execute("SELECT pg_terminate_backend(%s)", (pid,))


@contextlib.contextmanager
def table_locked(dsn, table):
    """Hold ``ACCESS EXCLUSIVE`` on *table* until the block ends."""
    with psycopg.connect(dsn) as conn:
        conn.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
        try:
            yield
        finally:
            conn.rollback()
