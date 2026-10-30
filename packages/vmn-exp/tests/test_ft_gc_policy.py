"""On a free-threaded build every collection is a full stop-the-world scan
of everything alive, frozen objects included (docs/plans/28-measurements.md
point 5), and the automatic trigger fires on RSS growth, which the
allocator's retention alone keeps causing. A 705k-run ui on 3.15t stopped
4-9 s per automatic collection, ten times in 45 minutes. A pause cannot get
shorter without fewer live objects (plan 26 F1), so past
:data:`FREE_THREADED_LARGE_RECORDS` runs a free-threaded ui runs fewer of
them: automatic collection off, and a ``vmn-gc`` thread collects on its own
clock, whether or not refreshes publish. The wait doubles from
:data:`GC_MIN_INTERVAL_SEC` to :data:`GC_MAX_INTERVAL_SEC` while collections
find little garbage, and halves when one finds much, so cyclic garbage stays
bounded. A GIL build, or a smaller store, is left alone."""
import gc
import threading
from types import SimpleNamespace

import pytest
from vmn_exp.core.gc_pause import gc_paused, set_automatic
from vmn_exp.core.gc_policy import (FREE_THREADED_LARGE_RECORDS, GC_MAX_INTERVAL_SEC,
                                    GC_MIN_INTERVAL_SEC, MUCH_GARBAGE, GcPolicy)
from vmn_exp.ui.gil_hint import FREE_THREADED_MAX_RECORDS
from vmn_exp.ui.refresher import Refresher

LARGE = FREE_THREADED_LARGE_RECORDS


@pytest.fixture(autouse=True)
def _gc_enabled():
    was = gc.isenabled()
    gc.enable()
    yield
    (gc.enable if was else gc.disable)()


def _policy(free_threaded=True, garbage=0):
    calls, started = [], []

    def collect():
        calls.append("collect")
        return garbage

    policy = GcPolicy(free_threaded=lambda: free_threaded, collect=collect,
                      set_automatic=lambda on: calls.append(("automatic", on)),
                      start=started.append)
    return policy, calls, started


def test_the_policy_starts_where_the_ui_stops_recommending_free_threaded():
    assert FREE_THREADED_LARGE_RECORDS == FREE_THREADED_MAX_RECORDS


def test_a_gil_build_serving_a_large_store_is_left_alone():
    policy, calls, started = _policy(free_threaded=False)
    policy.after_publish(LARGE * 3)
    assert calls == [] and started == []
    assert policy.stats()["active"] is False


def test_a_free_threaded_build_serving_a_small_store_is_left_alone():
    policy, calls, started = _policy()
    policy.after_publish(LARGE - 1)
    assert calls == [] and started == []
    assert policy.stats()["active"] is False


def test_a_large_store_on_free_threaded_turns_automatic_collection_off_and_starts_a_collector():
    policy, calls, started = _policy()
    policy.after_publish(LARGE)
    policy.after_publish(LARGE)
    assert calls == [("automatic", False)]
    assert len(started) == 1
    assert policy.stats()["active"] is True


def test_a_publish_does_not_collect():
    policy, calls, _ = _policy()
    for _ in range(5):
        policy.after_publish(LARGE)
    assert "collect" not in calls


def test_the_wait_doubles_up_to_the_cap_while_collections_find_little():
    policy, _, _ = _policy(garbage=MUCH_GARBAGE - 1)
    policy.after_publish(LARGE)
    assert policy.stats()["interval_sec"] == GC_MIN_INTERVAL_SEC
    waits = [policy.collect_now() for _ in range(8)]
    assert waits[0] == GC_MIN_INTERVAL_SEC * 2
    assert waits[-1] == GC_MAX_INTERVAL_SEC
    assert waits == sorted(waits)


def test_the_wait_halves_down_to_the_floor_when_a_collection_finds_much():
    policy, _, _ = _policy(garbage=0)
    for _ in range(8):
        policy.collect_now()
    policy._collect = lambda: MUCH_GARBAGE
    assert policy.collect_now() == GC_MAX_INTERVAL_SEC / 2
    waits = [policy.collect_now() for _ in range(8)]
    assert waits[-1] == GC_MIN_INTERVAL_SEC


def test_the_collector_thread_collects_without_any_publish():
    collected = threading.Event()
    policy = GcPolicy(free_threaded=lambda: True, set_automatic=lambda on: None,
                      collect=lambda: collected.set() or 0, min_interval=0.01,
                      max_interval=0.02)
    policy.after_publish(LARGE)
    assert collected.wait(5)
    names = [t.name for t in threading.enumerate()]
    assert "vmn-gc" in names
    policy.stop()


def test_stats_say_how_often_how_long_and_how_much_it_collected():
    policy, _, _ = _policy(garbage=7)
    policy.after_publish(LARGE)
    policy.collect_now()
    policy.collect_now()
    stats = policy.stats()
    assert stats["collections"] == 2 and stats["garbage"] == 14 and stats["last_garbage"] == 7
    assert stats["interval_sec"] == GC_MIN_INTERVAL_SEC * 4
    assert stats["last_at"] is not None and stats["last_ms"] >= 0 and stats["total_ms"] >= 0


def test_the_real_collect_does_not_freeze():
    gc.unfreeze()
    policy = GcPolicy(free_threaded=lambda: True, set_automatic=lambda on: None,
                      start=lambda target: None)
    policy.collect_now()
    assert gc.get_freeze_count() == 0


def test_automatic_collection_turned_off_inside_a_pause_stays_off_after_it():
    with gc_paused():
        with gc_paused():
            set_automatic(False)
        assert not gc.isenabled()
    assert not gc.isenabled()


def test_a_pause_after_automatic_collection_went_off_does_not_turn_it_back_on():
    set_automatic(False)
    assert not gc.isenabled()
    with gc_paused():
        pass
    assert not gc.isenabled()


def test_automatic_collection_turned_back_on_inside_a_pause_resumes_after_it():
    gc.disable()
    with gc_paused():
        set_automatic(True)
        assert not gc.isenabled()
    assert gc.isenabled()


def test_the_refresher_hands_each_publish_to_the_policy():
    noted = []
    refresher = Refresher(interval_sec=0.01, idle_sec=5)
    refresher.gc_policy = SimpleNamespace(after_publish=noted.append)
    refresher._after_refresh(object(), SimpleNamespace(rows=[1, 2, 3]))
    assert noted == [3]
