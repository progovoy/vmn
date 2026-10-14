"""A board's base keeps 100k rows alive for its whole generation; the cyclic
collector re-scanning them made full collections pause any request by
60-140 ms. A built or derived base is moved out of the collected generations
(``gc.freeze``), and since the rows hold no cycles an old base is still freed
by reference counting once the caches drop it."""
import gc
import weakref

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture(autouse=True)
def _unfrozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    gc.unfreeze()
    yield
    gc.unfreeze()


def _fleet():
    fleet = Fleet(5)
    fleet.seed(2000, T0, sweeps=4, live=10)
    return fleet


def test_a_built_base_leaves_the_collected_generations():
    fleet, cache = _fleet(), LeaderboardCache()
    snap = fleet.snapshot()

    cache.page(snap, SCHEMA, sort="loss", limit=50)

    assert gc.get_freeze_count() >= len(snap.rows)


def test_a_derived_base_leaves_the_collected_generations_too():
    fleet, cache = _fleet(), LeaderboardCache()
    cache.page(fleet.snapshot(), SCHEMA, sort="loss", limit=50)
    gc.unfreeze()
    fleet.mutate(T0, 20, reparent=False)

    cache.page(fleet.snapshot(), SCHEMA, sort="loss", limit=50)

    assert gc.get_freeze_count() > 0


def test_an_old_base_is_still_freed_once_the_caches_drop_it():
    fleet, cache = _fleet(), LeaderboardCache()
    snap = fleet.snapshot()
    cache.page(snap, SCHEMA, sort="loss", limit=50)
    first = weakref.ref(cache._base(snap)[0])
    del snap
    gc.disable()
    try:
        for _ in range(30):
            fleet.mutate(T0, 20, reparent=False)
            cache.page(fleet.snapshot(), SCHEMA, sort="loss", limit=50)
        assert first() is None
    finally:
        gc.enable()
