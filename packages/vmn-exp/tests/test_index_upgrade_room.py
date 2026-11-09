"""Plan 33 §2.4: an upgrade that builds a fresh generation file first checks
there is room on the disk for one as big as the file it replaces; without
it, it refuses — naming the bytes it needs and the path — rather than
filling the disk."""
import logging
import os
import shutil
import sqlite3
from collections import namedtuple

from vmn_exp.core import sqlite_files
from vmn_exp.core.index_store import SqliteStore

APP = "app"
_Usage = namedtuple("_Usage", "total used free")


def _outdated(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    store = SqliteStore(path)
    store.save(APP, {f"k{i}": {"verstr": str(i), "meta": {"verstr": str(i)}}
                     for i in range(50)}, set())
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = 'exp-index-10' WHERE k = 'schema'")
    conn.commit()
    conn.close()
    return path


def _free(monkeypatch, free):
    asked = []

    def disk_usage(path):
        asked.append(path)
        return _Usage(10 ** 12, 10 ** 12 - free, free)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)
    return asked


def test_an_upgrade_without_room_for_a_new_generation_refuses(tmp_path, monkeypatch, caplog):
    path = _outdated(tmp_path)
    size = os.path.getsize(path)
    asked = _free(monkeypatch, size - 1)

    with caplog.at_level(logging.WARNING):
        store = SqliteStore(path)

    assert asked
    assert store.connection() is None
    assert not sqlite_files._generations(path)
    assert sqlite_files.live_path(path) == path
    [warning] = [r.getMessage() for r in caplog.records if path in r.getMessage()]
    assert str(size) in warning and str(tmp_path) in warning


def test_an_upgrade_with_room_builds_its_new_generation(tmp_path, monkeypatch):
    path = _outdated(tmp_path)
    _free(monkeypatch, os.path.getsize(path) * 2)

    store = SqliteStore(path)

    assert store.connection() is not None
    assert sorted(sqlite_files._generations(path)) == [1]
