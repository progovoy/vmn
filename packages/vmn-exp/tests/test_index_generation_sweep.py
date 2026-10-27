"""Superseded index generations get deleted once nothing holds them (a stale
4.5 GB ``<name>.1.sqlite`` stayed for days): on a store's open, when a
connection follows a flipped pointer, and on the server's cache tick —
never while any process still has the file open."""
import os
import sqlite3
import subprocess
import sys

from vmn_exp.core import sqlite_files
from vmn_exp.core.index_point import shared_store
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.cache_rebuild import SqliteSwap
from vmn_exp.ui.cache_resync import WorkspaceCache

APP = "app"


def _rec(key):
    return {key: {"verstr": key, "meta": {"verstr": key}}}


def _rebuild(path, key="new"):
    swap = SqliteSwap(path)
    swap.store_for(APP).save(APP, _rec(key), set())
    swap.commit()


def _held(path):
    """A raw connection that has *path* open (as another reader would)."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("SELECT COUNT(*) FROM exp_index").fetchone()
    return conn


def _with_side_files(file):
    return [f for f in (file, file + "-wal", file + "-shm") if os.path.exists(f)]


def test_the_old_file_goes_once_its_connection_follows_the_flip(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    live = SqliteStore(path)
    live.save(APP, _rec("old"), set())
    _rebuild(path)
    assert os.path.exists(path) and os.path.exists(path + "-wal")  # live holds it

    assert set(live.load(APP)) == {"new"}  # switches to the new file
    assert _with_side_files(path) == []


def test_a_replaced_shared_store_is_closed_and_its_file_removed(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    first = shared_store(path)
    first.save(APP, _rec("old"), set())
    _rebuild(path)

    second = shared_store(path)
    assert second is not first and first._db.conn is None
    assert _with_side_files(path) == []
    assert set(second.load(APP)) == {"new"}


def test_a_store_opening_sweeps_what_an_earlier_flip_left(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, _rec("old"), set())
    holder = _held(path)
    _rebuild(path)
    assert os.path.exists(path)
    holder.close()

    SqliteStore(path)
    assert _with_side_files(path) == []


def test_the_cache_tick_sweeps_superseded_files(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    live = SqliteStore(path)
    live.save(APP, _rec("old"), set())
    holder = _held(path)
    clock = [100.0]
    cache = WorkspaceCache("ws", path, check_sec=0, clock=lambda: clock[0])
    _rebuild(path)
    live.load(APP)  # its own connection moved on; *holder* still has the file

    cache.tick()
    cache.tidy.wait(10)
    assert os.path.exists(path)

    holder.close()
    cache.tick()  # throttled: too soon after the last tidy
    cache.tidy.wait(10)
    assert os.path.exists(path)
    clock[0] += 3600
    cache.tick()
    cache.tidy.wait(10)
    assert _with_side_files(path) == []
    assert set(SqliteStore(path).load(APP)) == {"new"}


def test_a_file_another_process_holds_is_never_deleted(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, _rec("old"), set())
    code = ("import sqlite3, sys; c = sqlite3.connect(sys.argv[1]);"
            " c.execute('SELECT COUNT(*) FROM exp_index').fetchone();"
            " print('ready', flush=True); sys.stdin.read()")
    other = subprocess.Popen([sys.executable, "-c", code, path],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline().strip() == "ready"
        _rebuild(path)
        live = SqliteStore(path)
        assert set(live.load(APP)) == {"new"}
        cache = WorkspaceCache("ws", path, check_sec=0)
        cache.tick()
        cache.tidy.wait(10)
        sqlite_files.sweep(path)
        assert os.path.exists(path)
    finally:
        other.communicate("")
    sqlite_files.sweep(path)
    assert _with_side_files(path) == []


def test_a_generation_newer_than_the_live_one_is_never_swept(tmp_path):
    # A rebuild in progress: its file is not live yet, and may be unheld
    # between its writes and the flip.
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, _rec("old"), set())
    building = sqlite_files.new_generation(path)
    SqliteStore(building).save(APP, _rec("new"), set())

    sqlite_files.sweep(path)
    SqliteStore(path)
    assert os.path.exists(building)
    sqlite_files.flip(path, building)
    sqlite_files.sweep(path)
    assert os.path.exists(building) and not os.path.exists(path)
