"""Plan 23 S7: the Jobs view split. ``top=jobs`` keeps the top-level runs
with children, ``top=singles`` those without, ``top=1`` both; the facets
count them (``jobs``/``singles``, the cache's ``top_counts``), moved on across generations."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_scope import top_filter

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(5)
    jobs = fleet.seed_jobs(3, 10, T0, live=4)
    singles = [fleet.append(state=fleet.ended(T0)) for _ in range(6)]
    return fleet, jobs, singles, LeaderboardCache()


def _verstrs(cache, snap, top, **params):
    page = cache.page(snap, SCHEMA, limit=1000, top=top, **params)
    return {r["verstr"] for r in page["rows"]}


def test_jobs_and_singles_split_the_top_level_runs(board):
    fleet, jobs, singles, cache = board
    snap = fleet.snapshot()
    assert _verstrs(cache, snap, "jobs") == set(jobs)
    assert _verstrs(cache, snap, "singles") == set(singles)
    assert _verstrs(cache, snap, True) == set(jobs) | set(singles)


def test_jobs_rows_carry_their_job_singles_none(board):
    fleet, jobs, singles, cache = board
    snap = fleet.snapshot()
    rows = cache.page(snap, SCHEMA, limit=100, top="jobs")["rows"]
    assert all(r["job"]["total"] == 10 for r in rows)
    rows = cache.page(snap, SCHEMA, limit=100, top="singles")["rows"]
    assert all(r["job"] is None for r in rows)


@pytest.mark.parametrize("text,top", [
    (None, False), ("", False), ("0", False), ("false", False), ("1", True),
    ("true", True), ("jobs", "jobs"), ("singles", "singles")])
def test_top_filter_reads_the_route_parameter(text, top):
    assert top_filter(text) == top


def test_an_unknown_top_is_refused():
    with pytest.raises(ValueError):
        top_filter("outers")


def test_facets_count_top_level_jobs_and_singles(board):
    fleet, jobs, singles, cache = board
    facets = cache.top_counts(fleet.snapshot())
    assert (facets["jobs"], facets["singles"]) == (len(jobs), len(singles))


def test_filtered_facets_count_the_filtered_top_level_rows(board):
    fleet, jobs, singles, cache = board
    facets = cache.top_counts(fleet.snapshot(), status="running")
    assert (facets["jobs"], facets["singles"]) == (len(jobs), 0)
    assert cache.top_counts(fleet.snapshot(), scope=jobs[0])["jobs"] == 0


@pytest.fixture
def big(monkeypatch):
    """Large enough for a generation's few changes to move counts on."""
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(9)
    fleet.seed_jobs(4, 100, T0, live=8)
    for _ in range(60):
        fleet.append(state=fleet.ended(T0))
    return fleet, LeaderboardCache()


@pytest.mark.parametrize("archived", [False, True])
def test_facet_counts_moved_across_generations_equal_fresh_ones(big, archived):
    fleet, cache = big
    for _ in range(12):
        fleet.mutate(T0, 6)
        snap = fleet.snapshot()
        got = cache.top_counts(snap, archived=archived)
        fresh = LeaderboardCache().top_counts(snap, archived=archived)
        assert (got["jobs"], got["singles"]) == (fresh["jobs"], fresh["singles"])
        shown = dict(archived=archived)
        assert got["jobs"] == len(_verstrs(cache, snap, "jobs", **shown))
        assert got["singles"] == len(_verstrs(cache, snap, "singles", **shown))


def test_moved_top_orders_equal_fresh_ones(big):
    fleet, cache = big
    for _ in range(12):
        fleet.mutate(T0, 6)
        snap = fleet.snapshot()
        for top in ("jobs", "singles"):
            got = cache.page(snap, SCHEMA, limit=1000, top=top, sort="loss")["rows"]
            fresh = LeaderboardCache().page(snap, SCHEMA, limit=1000, top=top, sort="loss")
            assert [r["verstr"] for r in got] == [r["verstr"] for r in fresh["rows"]]
