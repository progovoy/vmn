"""Bulk index work pauses the cyclic garbage collector (plan 23 S9).

Loading 100k persisted records allocates ~20M containers that all live on;
every collection on the way traversed them again, which took a restart's
load from ~1s to ~4s. :func:`gc_paused` pauses collection for such a
stretch and restores it after, even when nested or entered from several
threads at once.
"""
import gc
import threading

import pytest

from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def _gc_enabled():
    was = gc.isenabled()
    gc.enable()
    yield
    (gc.enable if was else gc.disable)()


def test_collection_is_paused_inside_and_restored_after():
    with gc_paused():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_a_nested_pause_restores_only_at_the_outer_exit():
    with gc_paused():
        with gc_paused():
            pass
        assert not gc.isenabled()
    assert gc.isenabled()


def test_an_error_inside_still_restores_collection():
    with pytest.raises(RuntimeError):
        with gc_paused():
            raise RuntimeError("boom")
    assert gc.isenabled()


def test_a_collector_disabled_by_the_caller_stays_disabled():
    gc.disable()
    with gc_paused():
        pass
    assert not gc.isenabled()


def test_overlapping_pauses_on_two_threads_restore_once_both_exit():
    inside, release = threading.Event(), threading.Event()

    def other():
        with gc_paused():
            inside.set()
            release.wait(10)

    thread = threading.Thread(target=other)
    with gc_paused():
        thread.start()
        inside.wait(10)
    assert not gc.isenabled()  # the other thread is still loading
    release.set()
    thread.join()
    assert gc.isenabled()


def test_loading_the_persisted_records_pauses_collection(tmp_path, monkeypatch):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save("app", "0.0.1-dev.abc.r1", {"verstr": "0.0.1-dev.abc.r1", "timestamp": "t"}, {})
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, "app", cache_path=db).refresh()
    seen = []
    real = SqliteStore.load
    monkeypatch.setattr(SqliteStore, "load",
                        lambda self, app: seen.append(gc.isenabled()) or real(self, app))

    ExperimentIndex(st, "app", cache_path=db).refresh()

    assert seen == [False]
    assert gc.isenabled()


def test_a_leaderboard_base_builds_with_collection_paused(tmp_path, monkeypatch):
    from vmn_exp.ui import leaderboard_cache
    from vmn_exp.ui.leaderboard_cache import LeaderboardCache

    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save("app", "0.0.1-dev.abc.r1", {"verstr": "0.0.1-dev.abc.r1", "timestamp": "t"}, {})
    snap = ExperimentIndex(st, "app").refresh().snapshot()
    seen = []
    real = leaderboard_cache.annotate_rows
    monkeypatch.setattr(leaderboard_cache, "annotate_rows",
                        lambda *a: seen.append(gc.isenabled()) or real(*a))

    LeaderboardCache().page(snap, {}, sort="idx", limit=50)

    assert seen == [False]
    assert gc.isenabled()
