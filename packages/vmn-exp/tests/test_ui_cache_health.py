"""Plan 11 §4.6: each tick detects a SQLite cache that was deleted, replaced,
corrupted or written by another schema."""
import os
import sqlite3

from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.cache_health import SqliteHealth


def _cache(tmp_path):
    path = str(tmp_path / "cache.sqlite")
    SqliteStore(path).save("app", {"k": {"meta": {}}}, ())
    return path


def test_a_healthy_cache_has_no_problem(tmp_path):
    assert SqliteHealth(_cache(tmp_path)).problem() is None


def test_a_deleted_cache(tmp_path):
    path = _cache(tmp_path)
    health = SqliteHealth(path)
    os.remove(path)
    assert health.problem() == "missing"


def test_a_replaced_cache(tmp_path):
    path = _cache(tmp_path)
    health = SqliteHealth(path)
    os.makedirs(tmp_path / "x")
    os.replace(_cache(tmp_path / "x"), path)
    assert health.problem() == "replaced"


def test_a_corrupt_cache(tmp_path):
    path = _cache(tmp_path)
    health = SqliteHealth(path)
    with open(path, "r+b") as f:
        f.write(b"not a database at all" * 10)
    assert health.problem() == "corrupt"


def test_another_schema_version(tmp_path):
    path = _cache(tmp_path)
    health = SqliteHealth(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = 'exp-index-0' WHERE k = 'schema'")
    conn.commit()
    conn.close()
    assert health.problem() == "schema"


def test_rearm_accepts_the_current_file(tmp_path):
    path = _cache(tmp_path)
    health = SqliteHealth(path)
    os.remove(path)
    _cache(tmp_path)
    health.rearm()
    assert health.problem() is None
