"""A request never waits unboundedly on another thread's slow build: past
the bound it answers from what the previous generation already has, and
keeps waiting only when there is nothing to answer from."""
import threading
import time

import pytest
from leaderboard_fleet import T0, Fleet
from test_fix_ui_refresher import _wait_for
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.memo import LRU

from vmn_exp.core import status as status_mod

DEFAULT = dict(sort="idx", offset=0, limit=200)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _fleet(seed=3):
    fleet = Fleet(seed)
    fleet.seed_jobs(3, 20, T0, live=2)
    return fleet


def _slow_build(monkeypatch, slow):
    """Base builds of *slow* block until the returned event is set."""
    release, new_base = threading.Event(), LeaderboardCache._new_base

    def blocked(self, snapshot, *args):
        if snapshot is slow:
            release.wait(5)
        return new_base(self, snapshot, *args)

    monkeypatch.setattr(LeaderboardCache, "_new_base", blocked)
    return release


def _building(cache):
    return _wait_for(lambda: cache._bases._in_flight)


def test_a_slow_new_generation_answers_from_the_previous_one(frozen, monkeypatch):
    fleet = _fleet()
    old = fleet.snapshot()
    fleet.append(state=fleet.ended(T0))
    new = fleet.snapshot()
    cache = LeaderboardCache(base_wait_sec=0.1)
    previous = cache.page(old, {}, **DEFAULT)
    release = _slow_build(monkeypatch, new)
    warming = threading.Thread(target=cache.warm, args=(new,), daemon=True)
    warming.start()
    try:
        assert _building(cache)
        started = time.monotonic()
        page = cache.page(new, {}, **DEFAULT)
        took = time.monotonic() - started
    finally:
        release.set()
        warming.join(5)
    assert took < 1.0
    assert page == previous
    assert cache.page(new, {}, **DEFAULT)["total"] == previous["total"] + 1


def _waits_for_the_build(cache, snap, release):
    """Whether a request for *snap* still waits while another thread builds
    its base; then its answer, once *release* lets the build finish."""
    warming = threading.Thread(target=cache.warm, args=(snap,), daemon=True)
    warming.start()
    answers = []
    try:
        assert _building(cache)
        request = threading.Thread(target=lambda: answers.append(cache.page(snap, {}, **DEFAULT)),
                                   daemon=True)
        request.start()
        request.join(0.3)
        waiting = request.is_alive()
    finally:
        release.set()
    request.join(5)
    warming.join(5)
    return waiting, answers[0]


def test_with_no_previous_generation_the_request_waits(frozen, monkeypatch):
    snap = _fleet().snapshot()
    cache = LeaderboardCache(base_wait_sec=0.05)
    waiting, answer = _waits_for_the_build(cache, snap, _slow_build(monkeypatch, snap))
    assert waiting
    assert answer["total"] == len(snap.rows)


def test_another_index_of_the_same_app_is_never_the_previous_answer(frozen, monkeypatch):
    mine, theirs = _fleet().snapshot(), _fleet(7).snapshot()
    cache = LeaderboardCache(base_wait_sec=0.05)
    cache.page(theirs, {}, **DEFAULT)
    waiting, answer = _waits_for_the_build(cache, mine, _slow_build(monkeypatch, mine))
    assert waiting
    assert answer["total"] == len(mine.rows)


def test_a_bounded_wait_takes_the_stale_value():
    lru, release = LRU(2), threading.Event()
    owner = threading.Thread(target=lru.get, args=("k", lambda: release.wait(5) and "new"),
                             daemon=True)
    owner.start()
    try:
        assert _wait_for(lambda: lru._in_flight)
        assert lru.get("k", lambda: "never", stale=lambda: "old", wait_sec=0.05) == "old"
    finally:
        release.set()
        owner.join(5)
    assert lru.get("k", lambda: "never") == "new"


def test_a_bounded_wait_without_a_stale_value_waits_for_the_build():
    lru, release = LRU(2), threading.Event()
    owner = threading.Thread(target=lru.get, args=("k", lambda: release.wait(5) and "new"),
                             daemon=True)
    owner.start()
    assert _wait_for(lambda: lru._in_flight)
    threading.Timer(0.2, release.set).start()
    assert lru.get("k", lambda: "never", stale=lambda: None, wait_sec=0.05) == "new"
    owner.join(5)
