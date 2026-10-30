"""The free-threaded GC policy (plan 26 F5) runs with automatic collection
off and freezes what survives each scheduled collection. That is safe only
while serving generations makes no cyclic garbage (nothing waits for a
collection that no longer comes on its own) and an old generation frozen
while alive is still freed by reference counting once the caches move past
it (else every freeze keeps one for good, the leak plan 26 risk "a wrong
freeze leaks" names)."""
import gc
import weakref

import pytest
from leaderboard_fleet import T0
from test_ui_generation_memory import SCHEMA, _fleet, _serve, _snapshot
from vmn_exp.core.gc_pause import freeze_long_lived
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod
from vmn_exp.snapshot import LocalSnapshotStorage

GENERATIONS = 50


@pytest.fixture(autouse=True)
def _collector_off(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    was = gc.isenabled()
    gc.unfreeze()
    gc.disable()
    yield
    gc.unfreeze()
    (gc.enable if was else gc.disable)()


def _publish(fleet, cache):
    snap = _snapshot(fleet)
    view = snap.summarized(SCHEMA)
    _serve(cache, view)
    refs = (weakref.ref(snap), weakref.ref(view), weakref.ref(cache._base(view)[0]))
    fleet.mutate(T0, 5, reparent=False)
    return refs


def test_serving_a_generation_makes_no_cyclic_garbage():
    fleet, cache = _fleet(), LeaderboardCache()
    _publish(fleet, cache)
    gc.collect()
    garbage = []
    for _ in range(20):
        _publish(fleet, cache)
        garbage.append(gc.collect())
    assert garbage == [0] * 20


def test_an_index_refresh_makes_no_cyclic_garbage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")

    def add(i):
        verstr = f"0.0.1-dev.abc.r{i}"
        st.save("app", verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})

    for i in range(200):
        add(i)
    index = ExperimentIndex(st, "app", cache_path=str(tmp_path / "idx.sqlite"))
    index.refresh()
    gc.collect()
    garbage = []
    try:
        for i in range(10):
            add(1000 + i)
            index.refresh()
            index.snapshot().summarized(SCHEMA)
            garbage.append(gc.collect())
    finally:
        index.close()
    assert garbage == [0] * 10


def test_generations_frozen_after_each_publish_are_still_freed():
    fleet, cache = _fleet(), LeaderboardCache()
    refs, frozen = [], []
    for _ in range(GENERATIONS):
        refs.append(_publish(fleet, cache))
        freeze_long_lived()
        frozen.append(gc.get_freeze_count())
    alive = [i for i, gen in enumerate(refs[:-5]) if any(ref() is not None for ref in gen)]
    assert alive == []
    assert frozen[-1] <= frozen[4] * 1.2, frozen
