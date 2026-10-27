"""A server that is never restarted must free each index generation once the
index and the ui caches move past it. At 486k runs a snapshot generation (and
its schema view, its board base) holds ~10 per-verstr maps; one kept alive
per generation grew a live server by 8 GB an hour.

Kept alive how: a snapshot and its schema view referred to each other, and
every board generation was moved out of the collected generations
(``gc.freeze``), so the collector never looked at the cycle again. And a
refresh paused the collector across hours of S3 listing and reads."""
import dataclasses
import gc
import weakref

import pytest
from leaderboard_fleet import APP, T0, Fleet
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.index_views import SchemaRows
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod
from vmn_exp.snapshot import LocalSnapshotStorage

SCHEMA = {"loss": {"goal": "min", "primary": True}}
MAX = {"loss": {"goal": "max", "primary": True}}
LOWEST, HIGHEST = -1.0, 99.0


@pytest.fixture(autouse=True)
def _collector(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    was = gc.isenabled()
    gc.unfreeze()
    gc.enable()
    yield
    gc.unfreeze()
    (gc.enable if was else gc.disable)()


class _Cycle:
    def __init__(self):
        self.me = self


def _parts(rows):
    """A repeated ``loss`` for every third row, so a schema view differs."""
    seen = {"last": 0.5, "first": 0.5, "mean": 0.5, "min": LOWEST, "max": HIGHEST}
    return {row["verstr"]: ({"loss": dict(seen)}, None) for row in rows[::3]}


def _snapshot(fleet):
    """The fleet's next generation with repeated metrics, its schema views
    sharing one memo like an index's (:class:`RowCache`): an unchanged row
    keeps its summarized row, so a board derives the next generation."""
    snap = fleet.snapshot()
    built = IndexSnapshot.build(
        APP, snap.generation, snap.rows, snap.run_states,
        observed_at=snap.run_state_observed_at, metric_parts=_parts(snap.rows),
    )
    return dataclasses.replace(built, _schema_rows=fleet.schema_rows)


def _fleet(n=600):
    fleet = Fleet(7)
    fleet.seed(n, T0, sweeps=4, live=10)
    fleet.schema_rows = SchemaRows()
    return fleet


def test_a_snapshot_and_its_schema_view_are_freed_by_reference_counting():
    snap = _snapshot(_fleet(60))
    view = snap.summarized(SCHEMA)
    assert view is not snap and snap.summarized(SCHEMA) is view
    refs = [weakref.ref(snap), weakref.ref(view)]
    gc.disable()
    del snap, view
    assert [ref() for ref in refs] == [None, None]


def test_a_view_outliving_its_snapshot_still_summarizes_from_the_raw_rows():
    snap = _snapshot(_fleet(60))
    verstr = next(iter(snap.metric_parts))
    raw = snap.row(verstr)["metrics"].get("loss")
    view = snap.summarized(SCHEMA)
    del snap
    assert view.row(verstr)["metrics"]["loss"] == LOWEST
    assert view.summarized(MAX).row(verstr)["metrics"]["loss"] == HIGHEST
    assert view.summarized(None).row(verstr)["metrics"].get("loss") == raw


def _serve(cache, view):
    cache.page(view, SCHEMA, sort="loss", limit=50)
    cache.page(view, SCHEMA, sort="loss", limit=50, top=True)
    cache.facets_payload(view)
    cache.groups(view, SCHEMA, "parent")
    cache.columns(view, SCHEMA, ["metrics.loss"], limit=100)
    cache.job_rollups(view, SCHEMA)
    cache.search(view, "r0001", 10)


def _generations(fleet, cache, count):
    """*count* generations served through *cache*, as weak references
    ``(snapshot, view, base)``, the fleet changing between them."""
    refs = []
    for _ in range(count):
        snap = _snapshot(fleet)
        view = snap.summarized(SCHEMA)
        _serve(cache, view)
        refs.append((weakref.ref(snap), weakref.ref(view), weakref.ref(cache._base(view)[0])))
        fleet.mutate(T0, 5, reparent=False)
    return refs


def test_old_generations_are_freed_once_the_caches_move_past_them():
    fleet, cache = _fleet(), LeaderboardCache()
    refs = _generations(fleet, cache, 8)
    gc.collect()
    assert [[ref() is None for ref in gen] for gen in refs[:4]] == [[True] * 3] * 4


def test_old_generations_need_no_cyclic_collection_to_be_freed():
    fleet, cache = _fleet(), LeaderboardCache()
    _generations(fleet, cache, 1)
    gc.disable()
    refs = _generations(fleet, cache, 8)
    assert [[ref() is None for ref in gen] for gen in refs[:4]] == [[True] * 3] * 4


def test_a_cycle_alive_when_a_generation_is_derived_is_still_collected():
    fleet, cache = _fleet(), LeaderboardCache()
    _generations(fleet, cache, 1)
    cycle = _Cycle()
    ref = weakref.ref(cycle)
    derived = _generations(fleet, cache, 1)[0][2]()
    assert derived.delta is not None  # moved on from the last base
    del cycle, derived
    gc.collect()
    assert ref() is None


def test_a_board_built_from_scratch_freezes_no_garbage_cycle():
    gc.disable()  # the old garbage stays where it is until the build
    cycle = _Cycle()
    gc.collect()  # it reaches the oldest generation, still referenced
    ref = weakref.ref(cycle)
    del cycle
    _generations(_fleet(), LeaderboardCache(), 1)
    gc.enable()
    gc.collect()
    assert ref() is None


class _Remote(LocalSnapshotStorage):
    """A remote store whose every call notes whether the collector is on."""

    seen = None

    def is_remote(self):
        return True

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if name.startswith(("list", "load", "read", "stat")) and callable(attr):
            seen = super().__getattribute__("seen")

            def noted(*args, **kwargs):
                seen.append((name, gc.isenabled()))
                return attr(*args, **kwargs)

            return noted
        return attr


def test_a_remote_refresh_lists_and_reads_with_the_collector_on(tmp_path):
    st = _Remote(str(tmp_path), area="runs")
    for i in range(3):
        verstr = f"0.0.1-dev.abc.r{i}"
        st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
    st.seen = []
    index = ExperimentIndex(st, APP, cache_path=str(tmp_path / "idx.sqlite"), full_sweep_sec=0)

    index.refresh()

    assert len(index.snapshot().rows) == 3
    assert st.seen and all(enabled for _, enabled in st.seen), st.seen
    assert gc.isenabled()
    index.close()
