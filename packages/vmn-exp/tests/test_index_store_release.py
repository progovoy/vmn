"""A store dropped without ``close()`` lets go of its file at once: a
``sqlite3.Connection`` sits in a reference cycle with its own statement cache
(CPython >= 3.11), so left to itself it would hold the file open until the
cyclic collector runs — and a superseded index generation could not be swept."""
import gc
import os

from vmn_exp.core import sqlite_files
from vmn_exp.core.index_store import SqliteStore

APP = "app"


def _rec(key):
    return {key: {"verstr": key, "meta": {"verstr": key}}}


def test_a_dropped_store_releases_its_file_without_a_collection(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    gc.disable()
    try:
        SqliteStore(path).save(APP, _rec("old"), set())
        assert sqlite_files.remove_if_unused(path)
    finally:
        gc.enable()
    assert not os.path.exists(path)
