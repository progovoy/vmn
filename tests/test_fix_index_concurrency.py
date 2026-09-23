"""The index database is shared by processes (CLI, SDK, vmn ui): a lock held
elsewhere may slow a refresh down, never break it or cost the cache."""
import sqlite3

import pytest

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core import experiment_index_store
from version_stamp.core.experiment_index import ExperimentIndex, direct_rows

APP = "app"


@pytest.fixture(autouse=True)
def short_busy_timeout(monkeypatch):
    monkeypatch.setattr(experiment_index_store, "_BUSY_TIMEOUT_MS", 50)


def _seeded(tmp_path, n=3):
    storage = get_snapshot_storage("local", vmn_root_path=str(tmp_path / "repo"),
                                   subdir="experiments")
    for i in range(n):
        v = f"0.0.1-dev.abc.r{i}"
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        storage.append_log_entry(APP, v, "w", {
            "timestamp": "t", "type": "metrics", "values": {"loss": i},
        })
    return storage


def _lock(path):
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    return blocker


def test_a_write_locked_cache_still_serves_current_rows(tmp_path):
    storage = _seeded(tmp_path)
    path = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(storage, APP, cache_path=path)
    index.refresh()

    blocker = _lock(path)
    try:
        storage.append_log_entry(APP, "0.0.1-dev.abc.r1", "w", {
            "timestamp": "u", "type": "metrics", "values": {"loss": 42},
        })
        index.refresh()
        assert index.rows() == direct_rows(storage, APP)[0]
    finally:
        blocker.rollback()


def test_opening_a_locked_cache_neither_fails_nor_deletes_it(tmp_path):
    storage = _seeded(tmp_path)
    path = str(tmp_path / "idx.sqlite")
    ExperimentIndex(storage, APP, cache_path=path).refresh()

    blocker = _lock(path)
    try:
        other = ExperimentIndex(storage, APP, cache_path=path)
        other.refresh()
        assert other.rows() == direct_rows(storage, APP)[0]
    finally:
        blocker.rollback()

    # The persisted records survived: a later index starts from them.
    rows = sqlite3.connect(path).execute("SELECT COUNT(*) FROM exp_index").fetchone()
    assert rows[0] == 3


def test_a_locked_shared_database_is_never_mistaken_for_a_corrupt_one(tmp_path):
    """The ui index file also holds other caches: locked must not mean deleted."""
    storage = _seeded(tmp_path)
    path = str(tmp_path / "shared.sqlite")
    owner = sqlite3.connect(path)
    owner.execute("CREATE TABLE cache (scope TEXT PRIMARY KEY, payload TEXT)")
    owner.execute("INSERT INTO cache VALUES ('ver:app', 'precious')")
    owner.commit()
    owner.close()

    blocker = _lock(path)  # rollback-journal mode: blocks WAL switch and DDL
    try:
        index = ExperimentIndex(storage, APP, cache_path=path)
        index.refresh()
        assert index.rows() == direct_rows(storage, APP)[0]
    finally:
        blocker.rollback()

    kept = sqlite3.connect(path).execute("SELECT payload FROM cache").fetchall()
    assert kept == [("precious",)]
