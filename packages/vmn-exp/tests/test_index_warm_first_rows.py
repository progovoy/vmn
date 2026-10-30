"""A warm restart serves the newest persisted rows at once — ``loading``
their share of every persisted run — and only then reads the rest back.
Reading every persisted row first is O(runs) before anything shows: at
~700k runs a recycled server showed an empty board for minutes."""
import threading

import pytest

import vmn_exp.core.index as index_module
from journal_index_helpers import APP, make, storage
from vmn_exp.core import index_lean_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore

N, FIRST = 30, 10


@pytest.fixture
def persisted(tmp_path, monkeypatch):
    """``(storage, index file)``: N runs a previous life indexed, on a
    store that says it is remote."""
    st = storage(tmp_path)
    for i in range(N):
        make(st, i)
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    monkeypatch.setattr(st, "is_remote", lambda: True, raising=False)
    monkeypatch.setattr(index_module, "FIRST_ROWS", FIRST)
    return st, db


@pytest.fixture
def held_full_read(monkeypatch):
    """The full read of the persisted rows waits for the event set."""
    release, real = threading.Event(), SqliteStore.load_warm
    monkeypatch.setattr(SqliteStore, "load_warm",
                        lambda self, app_name: release.wait(10) and real(self, app_name))
    yield release
    release.set()


def test_a_warm_restart_serves_the_newest_rows_before_reading_them_all(persisted, held_full_read):
    st, db = persisted
    index = ExperimentIndex(st, APP, cache_path=db)

    first = index.snapshot_now(wait_sec=5)
    held_full_read.set()
    full = index.snapshot()

    assert len(full.rows) == N and full.loading is None
    newest = full.rows[-FIRST:]
    assert first.loading == (FIRST, N)
    assert [r["verstr"] for r in first.rows] == [r["verstr"] for r in newest]
    assert [r["idx"] for r in first.rows] == [r["idx"] for r in newest]
    assert all(first.status_of(r["verstr"]) == full.status_of(r["verstr"]) for r in newest)


def test_the_first_rows_decode_only_their_own(persisted, held_full_read, monkeypatch):
    st, db = persisted
    decoded, real = [], index_lean_store.decode_row
    monkeypatch.setattr(index_lean_store, "decode_row",
                        lambda idx, text: decoded.append(idx) or real(idx, text))
    index = ExperimentIndex(st, APP, cache_path=db)

    assert len(index.snapshot_now(wait_sec=5).rows) == FIRST
    assert len(decoded) == FIRST


def test_a_blocking_snapshot_still_answers_every_persisted_row(persisted, held_full_read):
    st, db = persisted
    index = ExperimentIndex(st, APP, cache_path=db)
    index.snapshot_now(wait_sec=5)
    answered = []
    reader = threading.Thread(target=lambda: answered.append(index.snapshot()))
    reader.start()
    reader.join(0.3)
    assert not answered  # the first rows are not the persisted snapshot
    held_full_read.set()
    reader.join(10)
    assert len(answered[0].rows) == N


def test_a_blocking_snapshot_answers_before_the_storage_listing_revalidates(persisted, monkeypatch):
    st, db = persisted
    listed = threading.Event()
    for name in ("list_files", "list_record_names"):
        real = getattr(st, name)
        monkeypatch.setattr(st, name, lambda *a, real=real, **kw: listed.wait(10) and real(*a, **kw))
    index = ExperimentIndex(st, APP, cache_path=db)
    answered = []
    reader = threading.Thread(target=lambda: answered.append(index.snapshot()))
    reader.start()
    reader.join(3)
    before_listing = list(answered)
    listed.set()
    reader.join(10)
    index.wait_revalidated()
    assert [len(snap.rows) for snap in before_listing] == [N]
