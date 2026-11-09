"""Plan 33 §2.1: one upgrader per index file. Threads and processes opening
an outdated file take turns under a lock (a thread lock and ``<path>.upgrade``
file lock); the one that gets it second re-reads the pointer and opens what
the first built, rather than building it again."""
import fcntl
import sqlite3
import threading
import time

from vmn_exp.core import index_store_upgrade, sqlite_files
from vmn_exp.core.index_store import SqliteStore, _connect

APP = "app"


def _outdated(tmp_path):
    """An index file holding records too old to copy."""
    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    store.save(APP, {"a": {"verstr": "1", "meta": {"verstr": "1"}}}, set())
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = 'exp-index-10' WHERE k = 'schema'")
    conn.commit()
    conn.close()
    return path


def _slow_flips(monkeypatch):
    """The generation files flipped to; each flip takes a while, so openers overlap."""
    flipped, real = [], sqlite_files.flip

    def flip(path, target):
        time.sleep(0.2)
        flipped.append(target)
        real(path, target)

    monkeypatch.setattr(sqlite_files, "flip", flip)
    return flipped


def test_threads_opening_an_outdated_file_build_one_generation(tmp_path, monkeypatch):
    path = _outdated(tmp_path)
    flipped = _slow_flips(monkeypatch)
    start, stores = threading.Barrier(3), []

    def open_store():
        start.wait()
        stores.append(SqliteStore(path))

    threads = [threading.Thread(target=open_store) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    assert len(flipped) == 1
    assert sorted(sqlite_files._generations(path)) == [1]
    assert {store.connection()[1] for store in stores} == {flipped[0]}


def test_an_opener_waits_for_another_process_upgrading_and_opens_its_generation(
        tmp_path, monkeypatch):
    path = _outdated(tmp_path)
    flipped = _slow_flips(monkeypatch)
    opened = []
    with open(path + ".upgrade", "a+") as held:  # another process's upgrade
        fcntl.flock(held, fcntl.LOCK_EX)
        opener = threading.Thread(target=lambda: opened.append(SqliteStore(path)))
        opener.start()
        opener.join(0.5)
        assert not opened and not sqlite_files._generations(path)
        conn, fresh = index_store_upgrade.regenerate(path, path, 10, _connect)
        conn.close()
    opener.join(20)

    assert flipped == [fresh]
    assert opened[0].connection()[1] == fresh
