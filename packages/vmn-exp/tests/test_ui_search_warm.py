"""Plan 23 S8b: the background refresher warms the search index after a new
generation, so the first search after a restart does not pay the build; a
schema view of a snapshot shares its search index."""
import dataclasses

import pytest
from leaderboard_fleet import T0
from search_fleet import TextFleet
from test_fix_ui_refresher import FakeIndex, _wait_for
from vmn_exp.ui import search_index
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.refresher import Refresher


@pytest.fixture
def snap():
    fleet = TextFleet(2)
    fleet.seed_jobs(2, 20, T0)
    return fleet.snapshot()


def _no_build(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("built on the request path")
    monkeypatch.setattr(search_index.SearchIndex, "build", classmethod(refuse))
    monkeypatch.setattr(search_index.SearchIndex, "moved", refuse)


def _view(snapshot):
    """A schema view of *snapshot* (what ``IndexSnapshot.summarized`` makes)."""
    rows = tuple(dict(row) for row in snapshot.rows)
    return dataclasses.replace(snapshot, rows=rows, _by_verstr={r["verstr"]: r for r in rows},
                               _views={}, _base=snapshot)


def test_a_warmed_snapshot_searches_without_a_build(snap, monkeypatch):
    cache = LeaderboardCache()
    cache.warm_search(snap)
    _no_build(monkeypatch)
    assert cache.search(snap, snap.rows[3]["verstr"], 5)["results"]


def test_a_schema_view_shares_its_snapshots_index(snap, monkeypatch):
    cache = LeaderboardCache()
    cache.warm_search(snap)
    _no_build(monkeypatch)
    view = _view(snap)
    found = cache.search(view, snap.rows[3]["verstr"], 5)["results"]
    assert found[0]["verstr"] == snap.rows[3]["verstr"]


def test_the_refresher_hands_each_refreshed_snapshot_on():
    seen = []
    refresher = Refresher(interval_sec=0.02, idle_sec=0.3, on_refresh=seen.append)
    try:
        index = FakeIndex()
        refresher.snapshot(index)
        assert _wait_for(lambda: len(set(seen)) >= 2)
        assert all(s[0] == "snapshot" for s in seen)
    finally:
        refresher.stop()


def test_a_failing_hand_on_keeps_refreshing():
    def boom(snapshot):
        raise RuntimeError("warm failed")
    refresher = Refresher(interval_sec=0.02, idle_sec=0.3, on_refresh=boom)
    try:
        index = FakeIndex()
        refresher.snapshot(index)
        assert _wait_for(lambda: index.refreshes >= 3)
    finally:
        refresher.stop()
