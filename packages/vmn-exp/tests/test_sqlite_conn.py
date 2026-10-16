"""Plan 25 F3: one SQLite connection policy for every cache file."""
import sqlite3

import pytest
from vmn_exp.core import sqlite_conn
from vmn_exp.core.sqlite_conn import connect, write_tx


def _pragma(conn, name):
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def test_connect_applies_the_policy(tmp_path):
    conn = connect(str(tmp_path / "a.sqlite"))
    assert _pragma(conn, "journal_mode") == "wal"
    assert _pragma(conn, "synchronous") == 1  # NORMAL
    assert _pragma(conn, "busy_timeout") == sqlite_conn.BUSY_TIMEOUT_MS
    assert _pragma(conn, "cache_size") == sqlite_conn.CACHE_SIZE
    assert _pragma(conn, "mmap_size") == sqlite_conn.MMAP_SIZE
    assert _pragma(conn, "temp_store") == 2  # MEMORY
    assert conn.isolation_level is None


def test_connect_takes_a_busy_timeout(tmp_path):
    conn = connect(str(tmp_path / "a.sqlite"), busy_timeout_ms=50)
    assert _pragma(conn, "busy_timeout") == 50


def test_write_tx_begins_immediate_and_commits(tmp_path):
    conn = connect(str(tmp_path / "a.sqlite"))
    statements = []
    conn.set_trace_callback(statements.append)
    with write_tx(conn):
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (1)")
    assert statements[0] == "BEGIN IMMEDIATE"
    assert statements[-1] == "COMMIT"
    other = sqlite3.connect(str(tmp_path / "a.sqlite"))
    assert other.execute("SELECT x FROM t").fetchall() == [(1,)]


def test_write_tx_rolls_back_on_error(tmp_path):
    conn = connect(str(tmp_path / "a.sqlite"))
    with write_tx(conn):
        conn.execute("CREATE TABLE t (x)")
    with pytest.raises(RuntimeError):
        with write_tx(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    assert not conn.in_transaction


def test_write_tx_holds_the_write_lock_from_its_start(tmp_path):
    path = str(tmp_path / "a.sqlite")
    conn = connect(path)
    other = connect(path, busy_timeout_ms=10)
    with write_tx(conn):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")


def test_readonly_connections_cannot_write(tmp_path):
    path = str(tmp_path / "a.sqlite")
    with write_tx(connect(path)) as conn:
        conn.execute("CREATE TABLE t (x)")
    ro = connect(path, readonly=True)
    assert ro.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.execute("INSERT INTO t VALUES (1)")


def test_in_chunks_yields_chunks_with_their_marks():
    from vmn_exp.core.sqlite_conn import in_chunks

    assert list(in_chunks(iter("abcde"), size=2)) == [
        (["a", "b"], "?, ?"), (["c", "d"], "?, ?"), (["e"], "?"),
    ]
    assert list(in_chunks([])) == []
    assert [len(chunk) for chunk, _ in in_chunks(range(1001))] == [500, 500, 1]


def test_read_tx_begins_and_commits_even_when_the_block_raises(tmp_path):
    from vmn_exp.core.sqlite_conn import read_tx

    conn = connect(str(tmp_path / "a.sqlite"))
    statements = []
    conn.set_trace_callback(statements.append)
    with read_tx(conn):
        conn.execute("SELECT 1")
    assert statements == ["BEGIN", "SELECT 1", "COMMIT"]
    with pytest.raises(RuntimeError):
        with read_tx(conn):
            raise RuntimeError("boom")
    assert statements[-1] == "COMMIT"
    assert not conn.in_transaction
