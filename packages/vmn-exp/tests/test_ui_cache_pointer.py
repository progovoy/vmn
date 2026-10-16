"""Plan 25 F3: the server's cache health and offline drop follow the pointer
file a rebuild flips."""
import os
import sqlite3

from vmn_exp.core import sqlite_files
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.index_store_schema import SCHEMA_VERSION
from vmn_exp.ui.cache_health import SqliteHealth
from vmn_exp.ui.cache_rebuild import SqliteSwap

APP = "app"


def _cache(path):
    SqliteStore(path).save(APP, {"k": {"meta": {}}}, ())
    return path


def _rebuild(path):
    swap = SqliteSwap(path)
    swap.store_for(APP).save(APP, {"k": {"meta": {}}}, ())
    swap.commit()


def test_health_after_a_rebuild_checks_the_new_file(tmp_path):
    path = _cache(str(tmp_path / "cache.sqlite"))
    health = SqliteHealth(path)
    _rebuild(path)
    health.rearm()
    assert not os.path.exists(path)  # swept: nothing held it
    assert health.problem() is None


def test_health_sees_a_flip_by_another_process_as_replaced(tmp_path):
    path = _cache(str(tmp_path / "cache.sqlite"))
    health = SqliteHealth(path)
    _rebuild(path)
    assert health.problem() == "replaced"


def test_health_sees_the_live_file_go_corrupt(tmp_path):
    path = _cache(str(tmp_path / "cache.sqlite"))
    _rebuild(path)
    health = SqliteHealth(path)
    with open(sqlite_files.live_path(path), "r+b") as f:
        f.write(b"not a database at all" * 10)
    assert health.problem() == "corrupt"


def test_a_newer_schema_is_no_problem_to_rebuild_over(tmp_path):
    path = _cache(str(tmp_path / "cache.sqlite"))
    health = SqliteHealth(path)
    prefix, number = SCHEMA_VERSION.rsplit("-", 1)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'schema'",
                 (f"{prefix}-{int(number) + 1}",))
    conn.commit()
    conn.close()
    assert health.problem() is None


def test_drop_removes_every_generation_and_the_pointer(tmp_path):
    path = _cache(str(tmp_path / "cache.sqlite"))
    _rebuild(path)
    sqlite_files.drop(path)
    assert os.listdir(tmp_path) == []
