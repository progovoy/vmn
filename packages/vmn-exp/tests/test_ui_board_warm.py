"""The refresher warms each new generation's default board answers: every
top view's newest-first first page (``top=jobs|singles|1`` and All runs, as
the web client asks for them) and the app's facets, so the first browser
request is a memo hit. A generation already superseded is not warmed."""
import pytest
from leaderboard_fleet import T0, Fleet
from test_fix_ui_refresher import _wait_for
from vmn_exp.ui import leaderboard_cache, leaderboard_facets
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.refresher import Refresher

from vmn_exp.core import status as status_mod

# What webui's firstPage sends: sort=idx, offset 0, limit PAGE_SIZE.
DEFAULT = dict(sort="idx", offset=0, limit=200)
TOPS = ("jobs", "singles", True, False)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _fleet():
    fleet = Fleet(3)
    fleet.seed_jobs(3, 40, T0, live=4)
    for _ in range(60):
        fleet.append(state=fleet.ended(T0))
    return fleet


class _Builds:
    """Counts the order and facet computations a request pays for."""

    def __init__(self, monkeypatch):
        self.calls = []
        static_of = LeaderboardCache._static_of
        counted = leaderboard_facets.Facets._counted
        monkeypatch.setattr(LeaderboardCache, "_static_of",
                            lambda s, *a: self.calls.append("order") or static_of(s, *a))
        monkeypatch.setattr(leaderboard_facets.Facets, "_counted",
                            lambda s, *a: self.calls.append("facets") or counted(s, *a))


def test_a_warmed_generation_answers_the_default_pages_from_the_memo(frozen, monkeypatch):
    snap = _fleet().snapshot()
    cache = LeaderboardCache()
    builds = _Builds(monkeypatch)
    cache.warm(snap)
    builds.calls.clear()
    for top in TOPS:
        page = cache.page(snap, {}, top=top, **DEFAULT)
        assert page["rows"], top
    cache.facets_payload(snap)
    assert builds.calls == []


def test_the_singles_page_is_newest_first(frozen):
    snap = _fleet().snapshot()
    rows = LeaderboardCache().page(snap, {}, top="singles", **DEFAULT)["rows"]
    idx = [row["idx"] for row in rows]
    assert idx == sorted(idx, reverse=True)
    assert all(row["kind"] == "single" for row in rows)


def test_after_a_refresh_publishes_the_default_singles_request_is_a_memo_hit(frozen, monkeypatch):
    fleet = _fleet()

    class FleetIndex:
        def __init__(self):
            self.snap = fleet.snapshot()

        def refresh(self):
            fleet.append(state=fleet.ended(T0))
            self.snap = fleet.snapshot()
            return self

        def snapshot(self):
            return self.snap

    cache = LeaderboardCache()
    warmed = []
    refresher = Refresher(interval_sec=0.02, idle_sec=5,
                          on_refresh=lambda s: cache.warm(s) or warmed.append(s))
    index = FleetIndex()
    try:
        refresher.snapshot(index)
        assert _wait_for(lambda: warmed)
    finally:
        refresher.stop()
    builds = _Builds(monkeypatch)
    cache.page(warmed[-1], {}, top="singles", **DEFAULT)
    assert builds.calls == []


def test_a_superseded_generation_is_not_warmed(frozen, monkeypatch):
    fleet = _fleet()
    old = fleet.snapshot()
    fleet.append(state=fleet.ended(T0))
    new = fleet.snapshot()
    cache = LeaderboardCache()
    cache.warm(new)
    builds = _Builds(monkeypatch)
    cache.warm(old)
    assert "order" not in builds.calls


def test_warming_never_fails_the_refresh(frozen, monkeypatch):
    monkeypatch.setattr(leaderboard_cache.LeaderboardCache, "page",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    cache = LeaderboardCache()
    cache.warm(_fleet().snapshot())  # logged, not raised
