"""DeltaLog's chain walk always ends and never holds the log's lock while it
works. An evicted base rebuilt for a held (older) snapshot is derived from
the newest kept base, so its move points *forward*: recording it made the
chain loop (A -> C -> B -> A ...), and ``since()`` then spun forever under
the lock, every ``add()`` (the board warm's new base) queued behind it."""
import threading
from collections import OrderedDict

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_delta import DeltaLog
from vmn_exp.ui.memo import LRU, Generations, TTLCache

from vmn_exp.core import status as status_mod

DEFAULT = dict(sort="idx", offset=0, limit=200)


class _Bounded(OrderedDict):
    """Moves whose lookups raise once a walk has clearly looped."""

    gets = 0

    def get(self, *args):
        self.gets += 1
        if self.gets > 10_000:
            raise RecursionError("the delta chain loops")
        return super().get(*args)


class _Base:
    def __init__(self, token, prev=None):
        self.token, self.rows = token, []
        self.delta = None if prev is None else (prev, [], [], [])


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _guarded(log):
    log._moves = _Bounded(log._moves)
    return log


def test_a_forward_move_never_makes_the_chain_loop():
    log = _guarded(DeltaLog())
    log.add(_Base(2, prev=1))
    log.add(_Base(3, prev=2))
    log.add(_Base(2, prev=3))  # generation 2 rebuilt from 3 after an eviction
    assert log.since(1, _Base(3)) is None


def test_a_valid_chain_still_composes():
    log = DeltaLog()
    log.add(_Base(2, prev=1))
    log.add(_Base(3, prev=2))
    assert log.since(1, _Base(3)) == ([], [])


def test_add_is_never_blocked_by_a_slow_walk():
    log = DeltaLog()
    log.add(_Base(2, prev=1))
    entered, release = threading.Event(), threading.Event()

    class Slow(OrderedDict):
        def get(self, *args):
            entered.set()
            release.wait(5)
            return super().get(*args)

    log._moves = Slow(log._moves)
    walker = threading.Thread(target=log.since, args=(1, _Base(2)), daemon=True)
    walker.start()
    entered.wait(0.5)
    adder = threading.Thread(target=log.add, args=(_Base(3, prev=2),), daemon=True)
    adder.start()
    adder.join(1)
    blocked = adder.is_alive()
    release.set()
    walker.join(5)
    assert not blocked


def test_a_held_snapshot_rebuilt_after_eviction_still_serves_orders(frozen):
    fleet = Fleet(3)
    fleet.seed_jobs(3, 40, T0, live=4)
    snaps = []
    for _ in range(4):
        fleet.append(state=fleet.ended(T0))
        snaps.append(fleet.snapshot())
    cache = LeaderboardCache()
    _guarded(cache._deltas)
    cache.page(snaps[0], {}, **DEFAULT)  # an order last served at generation 0
    for snap in snaps[1:]:
        cache._base(snap)
    cache._base(snaps[1])  # evicted (two bases kept), rebuilt from the newest
    page = cache.page(snaps[3], {}, **DEFAULT)
    assert page == LeaderboardCache().page(snaps[3], {}, **DEFAULT)


@pytest.mark.parametrize("make", [
    lambda: DeltaLog()._lock,
    lambda: LRU(2)._lock,
    lambda: Generations(2)._lock,
    lambda: TTLCache(1)._lock,
    lambda: LeaderboardCache()._warmer._lock,
    lambda: LeaderboardCache()._facets._lock,
    lambda: LeaderboardCache()._top_counts._lock,
    lambda: LeaderboardCache()._search._lock,
])
def test_the_board_locks_show_in_diag_dumps(make):
    assert isinstance(make(), TracedLock)
