"""An index file's WAL stays bounded: a long-lived server connection never
keeps the WAL at its peak size (a 4.6 GB ``-wal`` at 486k runs)."""
import os
import sqlite3
import time

import pytest
from vmn_exp.core import sqlite_conn, sqlite_files
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.sqlite_conn import connect

APP = "app"
LIMIT = 256 << 10


@pytest.fixture(autouse=True)
def small_limit(monkeypatch):
    monkeypatch.setattr(sqlite_conn, "JOURNAL_SIZE_LIMIT", LIMIT)


def _records(n, start=0):
    return {f"k{i}": {"meta": {"verstr": f"k{i}", "blob": "x" * 2000}}
            for i in range(start, start + n)}


def _wal_size(path):
    wal = sqlite_files.live_path(path) + "-wal"
    return os.path.getsize(wal) if os.path.exists(wal) else 0


def _reader(path):
    """A raw connection inside a read transaction: no checkpoint can finish."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("BEGIN")
    conn.execute("SELECT COUNT(*) FROM exp_index").fetchone()
    return conn


def test_connect_limits_the_journal_size(tmp_path):
    conn = connect(str(tmp_path / "a.sqlite"))
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == LIMIT


def test_a_big_save_leaves_the_wal_under_the_limit(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    other = SqliteStore(path)  # a second long-lived connection, idle
    assert other.count(APP) == 0
    assert store.save(APP, _records(600), set()) is True
    assert _wal_size(path) <= LIMIT
    assert set(other.load(APP)) == set(_records(600))


def test_a_busy_checkpoint_is_brief_and_retried_by_the_next_save(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    store.save(APP, _records(1), set())
    reader = _reader(path)
    started = time.monotonic()
    assert store.save(APP, _records(600, 1), set()) is True
    assert time.monotonic() - started < sqlite_conn.BUSY_TIMEOUT_MS / 1000
    assert _wal_size(path) > LIMIT  # the reader still needs the WAL
    reader.execute("COMMIT")
    reader.close()

    assert store.save(APP, _records(1, 700), set()) is True
    assert _wal_size(path) <= LIMIT


def test_checkpoint_answers_whether_it_finished(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    store.save(APP, _records(1), set())
    conn = connect(path)
    reader = _reader(path)
    store.save(APP, _records(200, 1), set())
    assert sqlite_conn.checkpoint(conn) is False
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == sqlite_conn.BUSY_TIMEOUT_MS
    reader.execute("COMMIT")
    assert sqlite_conn.checkpoint(conn) is True
    assert _wal_size(path) == 0


def test_a_rebuild_leaves_no_big_wal_behind(tmp_path):
    from vmn_exp.ui.cache_rebuild import SqliteSwap

    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, _records(1), set())
    swap = SqliteSwap(path)
    swap.store_for(APP).save(APP, _records(600), set())
    swap.commit()
    assert _wal_size(path) <= LIMIT
    assert len(SqliteStore(path).load(APP)) == 600


def test_the_cache_tick_checkpoints_a_wal_no_write_came_to_cut(tmp_path):
    from vmn_exp.ui.cache_resync import WorkspaceCache

    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    store.save(APP, _records(1), set())
    reader = _reader(path)
    store.save(APP, _records(600, 1), set())  # its checkpoint was kept busy
    reader.execute("COMMIT")
    reader.close()
    assert _wal_size(path) > LIMIT

    cache = WorkspaceCache("ws", path, check_sec=0)
    cache.tick()
    cache.tidy.wait(10)
    assert _wal_size(path) <= LIMIT
    assert len(store.load(APP)) == 601
