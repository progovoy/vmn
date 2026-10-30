"""On a free-threaded build every collection is a full stop-the-world scan
(the generation argument is ignored), and the automatic trigger fires on RSS
growth, which the allocator's retention alone keeps causing. A 705k-run ui on
3.15t stopped 4-9 s per automatic collection, at random moments on any
thread. So past :data:`FREE_THREADED_LARGE_RECORDS` runs a free-threaded ui
turns automatic collection off and collects on the refresher thread right
after a publish, at most every :data:`GC_MIN_INTERVAL_SEC`, freezing what
survives so the next one scans only what is new (plan 26 F5). A GIL build,
or a smaller store, is left alone."""
import gc
from types import SimpleNamespace

import pytest
from vmn_exp.core.gc_pause import gc_paused, set_automatic
from vmn_exp.core.gc_policy import FREE_THREADED_LARGE_RECORDS, GC_MIN_INTERVAL_SEC, GcPolicy
from vmn_exp.ui.gil_hint import FREE_THREADED_MAX_RECORDS
from vmn_exp.ui.refresher import Refresher

LARGE = FREE_THREADED_LARGE_RECORDS


@pytest.fixture(autouse=True)
def _gc_enabled():
    was = gc.isenabled()
    gc.enable()
    yield
    (gc.enable if was else gc.disable)()


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _policy(free_threaded=True):
    calls, clock = [], _Clock()
    policy = GcPolicy(free_threaded=lambda: free_threaded, clock=clock,
                      collect=lambda: calls.append("collect"),
                      set_automatic=lambda on: calls.append(("automatic", on)))
    return policy, calls, clock


def test_the_policy_starts_where_the_ui_stops_recommending_free_threaded():
    assert FREE_THREADED_LARGE_RECORDS == FREE_THREADED_MAX_RECORDS


def test_a_gil_build_serving_a_large_store_is_left_alone():
    policy, calls, _ = _policy(free_threaded=False)
    policy.after_publish(LARGE * 3)
    assert calls == []
    assert policy.stats()["active"] is False


def test_a_free_threaded_build_serving_a_small_store_is_left_alone():
    policy, calls, _ = _policy()
    policy.after_publish(LARGE - 1)
    assert calls == []
    assert policy.stats()["active"] is False


def test_a_large_store_on_free_threaded_turns_automatic_collection_off_then_collects():
    policy, calls, _ = _policy()
    policy.after_publish(LARGE)
    assert calls == [("automatic", False), "collect"]
    assert policy.stats()["active"] is True


def test_collections_are_at_most_one_per_interval():
    policy, calls, clock = _policy()
    policy.after_publish(LARGE)
    clock.now += GC_MIN_INTERVAL_SEC - 1
    policy.after_publish(LARGE)
    assert calls.count("collect") == 1
    clock.now += 1
    policy.after_publish(LARGE)
    assert calls.count("collect") == 2
    assert calls.count(("automatic", False)) == 1


def test_the_policy_stays_on_once_on():
    policy, calls, clock = _policy()
    policy.after_publish(LARGE)
    clock.now += GC_MIN_INTERVAL_SEC
    policy.after_publish(10)
    assert calls.count("collect") == 2
    assert ("automatic", True) not in calls


def test_stats_say_how_often_and_how_long_it_collected():
    policy, _, clock = _policy()
    policy.after_publish(LARGE)
    clock.now += GC_MIN_INTERVAL_SEC
    policy.after_publish(LARGE)
    stats = policy.stats()
    assert stats["collections"] == 2
    assert stats["interval_sec"] == GC_MIN_INTERVAL_SEC
    assert stats["last_at"] is not None and stats["last_ms"] >= 0 and stats["total_ms"] >= 0


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
