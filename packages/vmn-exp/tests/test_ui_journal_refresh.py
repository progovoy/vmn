"""Plan 11 §5.2 / phase 2c: the ui reads one change journal per workspace and
routes its entries by ``(area, app)`` to the watched indexes' ``hint``."""
import time

import pytest

from vmn_exp.core.index_store import SqliteStore
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.journal_sinks import journal_list_fn
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage
from vmn_exp.ui.journal_follow import WorkspaceJournal
from vmn_exp.ui.refresher import Refresher

FINISHED = "state: finished\nexit_code: 0\n"


class FakeIndex:
    def __init__(self, app_name):
        self.app_name = app_name
        self.hints, self.reconciles, self.journaled = [], 0, False

    def hint(self, name):
        self.hints.append(name)

    def reconcile(self):
        self.reconciles += 1


@pytest.fixture
def store(tmp_path):
    return journaled(LocalSnapshotStorage(str(tmp_path), "runs"), writer_id="w1")


@pytest.fixture
def lists(store):
    calls = []
    real = journal_list_fn(store)

    def list_fn(prefix, start_after=None):
        calls.append(prefix)
        return real(prefix, start_after)

    return calls, list_fn


def _write(store, app, verstr):
    store.save(app, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})


def _journal(list_fn, cache=None, **kw):
    return WorkspaceJournal(list_fn, cache or SqliteStore(":memory:"), "ws", **kw)


def test_entries_are_routed_to_the_watched_scope_only(store, lists):
    _, list_fn = lists
    journal = _journal(list_fn)
    watched, other = FakeIndex("app"), FakeIndex("other")
    journal.watch(watched)
    journal.watch(other)
    _write(store, "app", "1.0.0-dev.a")
    _write(store, "unwatched", "1.0.0-dev.b")
    journal.tick()
    assert watched.hints == ["1.0.0-dev.a"]
    assert other.hints == []
    assert watched.journaled


def test_entries_are_hinted_once(store, lists):
    _, list_fn = lists
    journal = _journal(list_fn)
    index = FakeIndex("app")
    journal.watch(index)
    _write(store, "app", "1.0.0-dev.a")
    journal.tick()
    journal.tick()
    assert index.hints == ["1.0.0-dev.a"]


def test_a_tick_lists_the_journal_the_same_for_200_apps_as_for_one(store, lists):
    calls, list_fn = lists
    clock = lambda: 1_800_000_000.0  # noqa: E731

    def listings(apps):
        journal = _journal(list_fn, clock=clock, skew_window_sec=0)
        for i in range(apps):
            journal.watch(FakeIndex(f"app{i}"))
        calls.clear()
        journal.tick()
        return len(calls)

    assert listings(200) == listings(1) == 1


def test_an_overflowing_scope_reconciles(store, lists):
    _, list_fn = lists
    journal = _journal(list_fn, max_per_scope=2)
    index = FakeIndex("app")
    journal.watch(index)
    reconciles = index.reconciles
    for i in range(3):
        _write(store, "app", f"1.0.0-dev.r{i}")
    journal.tick()
    assert index.hints == [] and index.reconciles == reconciles + 1


def test_a_new_watch_reconciles_and_an_unwatched_scope_is_dropped(store, lists):
    _, list_fn = lists
    journal = _journal(list_fn)
    index = FakeIndex("app")
    journal.watch(index)
    assert index.reconciles == 1
    journal.unwatch(index)
    _write(store, "app", "1.0.0-dev.a")
    journal.tick()
    assert index.hints == []


def test_the_cursor_persists_in_the_cache_store(store, lists, tmp_path):
    _, list_fn = lists
    cache = SqliteStore(str(tmp_path / "cache.sqlite"))
    clock = lambda: 1_800_000_000.0  # noqa: E731
    _journal(list_fn, cache, clock=clock).tick()
    reopened = _journal(list_fn, SqliteStore(str(tmp_path / "cache.sqlite")))
    assert reopened.cursor == {"last_seen_ms": 1_800_000_000_000}


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_the_refresher_shows_a_new_run_through_the_journal(tmp_path):
    from vmn_exp.core.index import ExperimentIndex

    root = str(tmp_path / "store")
    writer = open_storage(None, root, area="runs")
    _write(writer, "app", "1.0.0-dev.a")
    reader = open_storage(None, root, area="runs", writer=False)
    index = ExperimentIndex(reader, "app", full_sweep_sec=3600)
    journal = _journal(journal_list_fn(reader))
    refresher = Refresher(interval_sec=0.02, idle_sec=60)
    try:
        assert len(refresher.snapshot(index, journal).rows) == 1
        names = []
        index.reconcile = lambda: names.append("full")  # no full listing from here on
        _write(writer, "app", "1.0.0-dev.b")
        writer.save_file("app", "1.0.0-dev.b", "run_state.yml", FINISHED)
        assert _wait_for(lambda: len(index.snapshot().rows) == 2)
        assert names == []
    finally:
        refresher.stop()


def test_a_tick_with_no_new_entries_does_not_rewrite_the_cursor(store, lists):
    _, list_fn = lists
    cache = SqliteStore(":memory:")
    puts = []
    real_put = cache.kv_put
    cache.kv_put = lambda *a: (puts.append(a), real_put(*a))
    journal = _journal(list_fn, cache)
    journal.watch(FakeIndex("app"))
    _write(store, "app", "1.0.0-dev.a")
    journal.tick()
    written = len(puts)
    journal.tick()
    journal.tick()
    assert written >= 1
    assert len(puts) == written
