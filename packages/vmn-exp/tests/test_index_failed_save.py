"""Plan 25 F3: a save that fails keeps its records dirty; the next refresh
writes them."""
import sqlite3

import pytest
from vmn_exp.core import index_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import open_storage

APP = "app"


@pytest.fixture(autouse=True)
def short_busy_timeout(monkeypatch):
    monkeypatch.setattr(index_store, "_BUSY_TIMEOUT_MS", 20)


def _save(storage, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
    return verstr


def _persisted(path):
    return set(SqliteStore(path).load(APP))


def test_a_busy_save_is_retried_by_the_next_refresh(tmp_path):
    storage = open_storage(root=str(tmp_path / "repo"), area="runs")
    first = _save(storage, 0)
    path = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(storage, APP, cache_path=path)
    index.refresh()
    assert _persisted(path) == {first}

    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")  # forces SQLITE_BUSY on the next save
    try:
        second = _save(storage, 1)
        index.refresh()
        assert {r["verstr"] for r in index.rows()} == {first, second}
    finally:
        blocker.execute("ROLLBACK")
    assert _persisted(path) == {first}

    index.refresh()  # nothing changed in storage since
    assert _persisted(path) == {first, second}


def test_a_failed_removal_is_retried_too(tmp_path):
    storage = open_storage(root=str(tmp_path / "repo"), area="runs")
    first, second = _save(storage, 0), _save(storage, 1)
    path = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(storage, APP, cache_path=path)
    index.refresh()

    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        storage.delete(APP, second)
        index.refresh()
    finally:
        blocker.execute("ROLLBACK")
    assert _persisted(path) == {first, second}

    index.refresh()
    assert _persisted(path) == {first}
