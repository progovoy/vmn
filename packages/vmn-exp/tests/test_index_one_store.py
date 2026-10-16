"""One command reads an app's persisted index through one store: one
connection to its file, one sync of it with storage, one lean index per
process index (the /simplify findings on plan 25)."""
import os
import sqlite3

import pytest
from similar_seed import seed, verstr
from vmn_exp.core import index_store, sqlite_files
from vmn_exp.core.index import ExperimentIndex, shared_index
from vmn_exp.core.index_list import list_view
from vmn_exp.core.index_point import index_path, shared_store
from vmn_exp.core.similar_search import find
from vmn_exp.snapshot import open_storage

APP = "trainer"


@pytest.fixture
def storage(tmp_path):
    st = open_storage(root=str(tmp_path / "store"), area="runs")
    seed(st, APP, verstr(1), intent={"text": "focal loss for imbalance"})
    seed(st, APP, verstr(2), intent={"text": "label smoothing"})
    return st


@pytest.fixture
def connects(monkeypatch):
    """The database files opened from now on, one entry per connection."""
    opened, real = [], sqlite3.connect

    def counting(target, *args, **kwargs):
        if sqlite_files.is_file_path(str(target)):
            opened.append(os.path.realpath(str(target)))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    return opened


@pytest.fixture
def listings(storage, monkeypatch):
    """Record-name listings of *storage* (no names signature: a remote store)."""
    calls = []
    monkeypatch.setattr(storage, "record_names_sig", lambda app: None, raising=False)
    for name in ("list_record_names", "list_record_keys"):
        real = getattr(storage, name)
        monkeypatch.setattr(storage, name, lambda app, _real=real: calls.append(app) or _real(app))
    return calls


def test_a_similar_search_opens_the_index_file_once(storage, connects):
    find(storage, APP, "latest", context="focal loss")
    path = os.path.realpath(sqlite_files.live_path(index_path(storage, APP)))
    assert connects.count(path) == 1


def test_a_warm_similar_search_lists_record_names_once(storage, listings):
    find(storage, APP, "latest", context="focal loss")
    listings.clear()
    find(storage, APP, "latest", context="focal loss")
    assert len(listings) == 1


def test_the_process_index_persists_through_the_shared_store(storage):
    path = index_path(storage, APP)
    assert shared_index(storage, APP)._store is shared_store(path)


def test_a_recreated_index_file_gets_a_new_store(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    first = shared_store(path)
    first.kv_put("s", "f", 1)
    os.remove(path)
    assert shared_store(path) is not first
    assert shared_store(path).kv_get("s", "f") is None


def test_repeated_syncs_load_the_persisted_rows_once(storage, monkeypatch):
    find(storage, APP, "latest", context="focal loss")  # persists the index
    index = ExperimentIndex(storage, APP, cache_path=index_path(storage, APP))
    loads = []
    real = index_store.SqliteStore.load_lazy
    monkeypatch.setattr(index_store.SqliteStore, "load_lazy",
                        lambda self, app: loads.append(app) or real(self, app))
    assert index.sync() and index.sync()
    assert len(loads) == 1


def test_a_listing_reads_through_the_index_store(storage, connects):
    assert list_view(storage, APP) is not None
    path = os.path.realpath(sqlite_files.live_path(index_path(storage, APP)))
    assert connects.count(path) == 1


def test_the_store_and_the_index_name_their_file(storage):
    path = index_path(storage, APP)
    index = shared_index(storage, APP)
    assert shared_store(path).path == path
    assert index.path == path
    assert ExperimentIndex(storage, APP).path is None


def test_index_path_is_none_without_a_cache_path():
    assert index_path(object(), APP) is None
