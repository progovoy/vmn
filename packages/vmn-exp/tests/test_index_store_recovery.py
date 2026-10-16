"""Plan 25 F3: never delete a live database's files; fail loudly once,
recover always."""
import logging
import os
import sqlite3

from vmn_exp.core import index_store, index_store_conn, sqlite_files
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.cache_rebuild import SqliteSwap

APP = "app"


def _rec(verstr):
    return {"verstr": verstr, "meta": {"verstr": verstr}}


def _files(tmp_path):
    return sorted(os.listdir(tmp_path))


def _reader(path):
    """A raw connection inside a read transaction on *path*."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("BEGIN")
    conn.execute("SELECT COUNT(*) FROM exp_index").fetchone()
    return conn


def test_a_rebuild_under_an_open_reader_loses_nothing(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    live = SqliteStore(path)
    live.save(APP, {"old": _rec("1")}, set())
    reader = _reader(path)

    swap = SqliteSwap(path)
    swap.store_for(APP).save(APP, {"new": _rec("2")}, set())
    swap.commit()

    # The reader keeps its file, WAL and all, and can still read it.
    assert os.path.exists(path) and os.path.exists(path + "-wal")
    assert reader.execute("SELECT key FROM exp_index").fetchall() == [("old",)]
    reader.execute("COMMIT")
    assert reader.execute("SELECT key FROM exp_index").fetchall() == [("old",)]
    # A new open, and the store that was open, see the new file.
    assert set(SqliteStore(path).load(APP)) == {"new"}
    assert set(live.load(APP)) == {"new"}
    assert sqlite_files.live_path(path) != path

    reader.close()
    live.close()
    sqlite_files.sweep(path)
    assert not os.path.exists(path)
    assert not os.path.exists(path + "-wal") and not os.path.exists(path + "-shm")
    assert set(SqliteStore(path).load(APP)) == {"new"}


def test_a_second_rebuild_moves_on_and_sweeps_the_first(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, {"a": _rec("1")}, set())
    for key in ("b", "c"):
        swap = SqliteSwap(path)
        swap.store_for(APP).save(APP, {key: _rec(key)}, set())
        swap.commit()
    assert set(SqliteStore(path).load(APP)) == {"c"}
    databases = [f for f in _files(tmp_path) if f.endswith(".sqlite")]
    assert databases == [os.path.basename(sqlite_files.live_path(path))]


def test_a_corrupt_file_is_rebuilt_beside_it(tmp_path, caplog):
    path = str(tmp_path / "idx.sqlite")
    with open(path, "wb") as f:
        f.write(b"not a database at all" * 100)
    caplog.set_level(logging.WARNING)
    store = SqliteStore(path)
    assert store.save(APP, {"a": _rec("1")}, set()) is True
    assert sqlite_files.live_path(path) != path
    assert set(SqliteStore(path).load(APP)) == {"a"}
    assert any(path in r.getMessage() for r in caplog.records)


def test_corruption_under_another_open_store_flips_it_over(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    other = SqliteStore(path)
    other.save(APP, {"a": _rec("1")}, set())
    store = SqliteStore(path)
    store._db.recover("simulated corruption")
    store.save(APP, {"b": _rec("2")}, set())
    # The other store's file was not deleted under it; it follows the flip.
    assert os.path.exists(path)
    assert set(other.load(APP)) == {"b"}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_an_open_failure_retries_with_backoff(tmp_path, monkeypatch, caplog):
    clock = _Clock()
    monkeypatch.setattr(index_store_conn, "_monotonic", clock)
    path = str(tmp_path / "missing-dir" / "idx.sqlite")
    caplog.set_level(logging.WARNING)
    store = SqliteStore(path)
    assert store.save(APP, {"a": _rec("1")}, set()) is False
    os.makedirs(tmp_path / "missing-dir")
    assert store.save(APP, {"a": _rec("1")}, set()) is False  # still backing off
    clock.now += 60
    assert store.save(APP, {"a": _rec("1")}, set()) is True
    assert set(SqliteStore(path).load(APP)) == {"a"}
    warnings = [r for r in caplog.records if path in r.getMessage()]
    assert len(warnings) == 1


def test_backoff_grows_while_failing(tmp_path, monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(index_store_conn, "_monotonic", clock)
    attempts = []
    real = index_store._connect

    def counted(file):
        attempts.append(clock.now)
        return real(file)

    monkeypatch.setattr(index_store, "_connect", counted)
    store = SqliteStore(str(tmp_path / "missing-dir" / "idx.sqlite"))
    for _ in range(200):
        clock.now += 0.5
        store.load(APP)
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    assert len(attempts) < 20 and gaps == sorted(gaps)


def test_a_failed_save_warns_once_and_reports_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("vmn_exp.core.sqlite_conn.BUSY_TIMEOUT_MS", 20)
    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    caplog.set_level(logging.WARNING)
    try:
        assert store.save(APP, {"a": _rec("1")}, set()) is False
        assert store.save(APP, {"b": _rec("2")}, set()) is False
    finally:
        blocker.execute("ROLLBACK")
    warnings = [r for r in caplog.records if path in r.getMessage()]
    assert len(warnings) == 1 and "locked" in warnings[0].getMessage()
    assert store.save(APP, {"c": _rec("3")}, set()) is True
