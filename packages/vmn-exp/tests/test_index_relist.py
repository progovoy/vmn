"""A journaled remote index's listings of every record run behind serving
and in parallel: a full listing lists the record names, then their files a
chunk at a time on several threads, the index applying each chunk under its
lock briefly; a journal overflow lists the names alone."""
import time

import pytest

from journal_index_helpers import (
    APP,
    Clock,
    FakeJournal,
    Spy,
    make,
    progress,
    settle,
    storage,
    verstrs,
)
from vmn_exp.core import index_relist
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.journal_follow import WorkspaceJournal


@pytest.fixture
def st(tmp_path):
    return storage(tmp_path)


def _journaled(st):
    index = ExperimentIndex(st, APP, full_sweep_sec=3600)
    index.journaled = True
    return index


def test_a_full_listing_lists_chunks_of_records_in_parallel(st, monkeypatch):
    monkeypatch.setattr(index_relist, "LISTING_CHUNK", 5)
    monkeypatch.setattr(index_relist, "LISTING_WORKERS", 4)
    runs = {make(st, i) for i in range(40)}
    spy = Spy(st, monkeypatch)
    index = settle(_journaled(st))
    assert verstrs(index) == runs
    assert spy.max_active > 1
    assert None not in spy.files


def test_the_progress_hook_follows_the_listing(st, monkeypatch):
    monkeypatch.setattr(index_relist, "LISTING_CHUNK", 5)
    monkeypatch.setattr(index_relist, "LISTING_WORKERS", 1)
    for i in range(4):
        make(st, i)
    spy = Spy(st, monkeypatch)
    index = settle(_journaled(st))  # a cold index waits for its listing
    for i in range(4, 20):
        make(st, i)
    spy.reset()
    spy.block_files_from = 3  # two of four chunks listed, then the store hangs
    index.reconcile()
    index.refresh()
    deadline = time.monotonic() + 5
    while progress(index)[1] != 0.5 and time.monotonic() < deadline:
        index.refresh()
        time.sleep(0.01)
    assert progress(index) == ("full_listing", 0.5)
    spy.release.set()
    settle(index)
    assert progress(index) == ("idle", None)
    assert len(verstrs(index)) == 20


def test_a_journal_overflow_lists_record_names_not_files(st, monkeypatch):
    clock = Clock()
    journal = FakeJournal()
    make(st, 0)
    spy = Spy(st, monkeypatch)
    ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock,
                          max_per_scope=2)
    index = ExperimentIndex(st, APP, full_sweep_sec=3600)
    ws.watch(index)
    settle(index)
    announced = [make(st, i) for i in range(1, 4)]
    for run in announced:
        journal.put(clock.t * 1000, run)
    unannounced = make(st, 9)
    spy.reset()

    ws.tick()  # three entries: an overflow
    settle(index)

    assert set(announced) | {unannounced} <= verstrs(index)
    assert spy.names >= 1
    assert None not in spy.files


def test_a_cache_rebuild_of_a_journaled_index_loads_every_record(st, monkeypatch):
    from vmn_exp.ui.cache_resync import _build

    runs = {make(st, i) for i in range(6)}
    Spy(st, monkeypatch)
    fresh = _build(st, APP, SqliteStore(":memory:"), _journaled(st))
    assert verstrs(fresh) == runs
    assert fresh.journaled


def test_a_burst_of_hints_is_listed_in_parallel_over_several_refreshes(st, monkeypatch):
    from vmn_exp.core import index_sweep_behind

    monkeypatch.setattr(index_relist, "LISTING_CHUNK", 5)
    monkeypatch.setattr(index_relist, "LISTING_WORKERS", 4)
    monkeypatch.setattr(index_sweep_behind, "HINTS_PER_REFRESH", 20)
    make(st, 0)
    spy = Spy(st, monkeypatch)
    index = settle(_journaled(st))
    burst = [make(st, i) for i in range(1, 41)]
    for run in burst:
        index.hint(run)
    spy.reset()

    index.refresh()
    assert len(verstrs(index)) == 21
    assert spy.max_active > 1
    settle(index)
    assert set(burst) <= verstrs(index)
