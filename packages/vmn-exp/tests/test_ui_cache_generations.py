"""The board's per-generation caches are keyed by a base token first and
sized for many filter combinations, so by size alone they kept 32 old index
generations: 333 MB of grouped views at 20k runs. Only an app's newest
generations are served, so each app keeps its newest GENERATIONS_KEPT and the
older ones' entries are dropped as it advances; other apps keep theirs."""
import weakref

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import GENERATIONS_KEPT, LeaderboardCache
from vmn_exp.ui.memo import LRU

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}
TOKENS_BELOW = 10**6  # base tokens count up from 1; id()-keyed entries are far larger


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _lrus(obj, depth=0, seen=None):
    seen = set() if seen is None else seen
    if id(obj) in seen or depth > 3:
        return
    seen.add(id(obj))
    for value in vars(obj).values():
        if isinstance(value, LRU):
            yield value
        elif type(value).__module__.startswith("vmn_exp.ui") and hasattr(value, "__dict__"):
            yield from _lrus(value, depth + 1, seen)


def _tokens(cache):
    """Every base token a per-generation cache entry is kept under."""
    out = set()
    for lru in _lrus(cache):
        for key in lru._entries:
            token = key[0] if isinstance(key, tuple) and key else key
            if isinstance(token, int) and not isinstance(token, bool) and token < TOKENS_BELOW:
                out.add(token)
    return out


def _serve(cache, snap):
    cache.page(snap, SCHEMA, sort="loss", limit=50)
    cache.groups(snap, SCHEMA, "parent", sort="loss", limit=50)
    cache.job_rollups(snap, SCHEMA)
    cache.page(snap, SCHEMA, sort="job:total", top="jobs", limit=50)
    return cache._base(snap)[0].token


def _fleet(seed):
    fleet = Fleet(seed)
    fleet.seed(1500, T0, sweeps=4, live=20)
    return fleet


def test_an_app_keeps_only_its_newest_generations():
    fleet, cache = _fleet(1), LeaderboardCache()
    tokens = []
    for _ in range(12):
        fleet.mutate(T0, 10, reparent=False)
        tokens.append(_serve(cache, fleet.snapshot()))

    assert _tokens(cache) <= set(tokens[-GENERATIONS_KEPT:])


def test_another_app_keeps_its_generation_while_one_advances():
    busy, idle = _fleet(1), _fleet(2)
    idle.app = "other"
    cache = LeaderboardCache()
    idle_snap = idle.snapshot()
    idle_token = _serve(cache, idle_snap)
    for _ in range(8):
        busy.mutate(T0, 10, reparent=False)
        _serve(cache, busy.snapshot())

    assert idle_token in _tokens(cache)


def test_an_old_snapshot_is_not_kept_alive_by_the_caches():
    fleet, cache = _fleet(1), LeaderboardCache()
    snap = fleet.snapshot()
    _serve(cache, snap)
    first = weakref.ref(snap)
    del snap
    for _ in range(GENERATIONS_KEPT + 3):
        fleet.mutate(T0, 10, reparent=False)
        _serve(cache, fleet.snapshot())

    assert first() is None
