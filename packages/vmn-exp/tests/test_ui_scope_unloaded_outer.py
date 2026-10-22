"""A store's cold load can index an outer run's inner runs before the outer
run's own record: a board scoped to it lists the inner runs it holds (and
their facets) instead of a 404, which stays for a run nothing names."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_scope import UnknownScope

from vmn_exp.core import status as status_mod

OUTER = "1.0.0-dev.outer"


@pytest.fixture
def loading(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(3)
    inners = [fleet.append(parent=OUTER, state=fleet.ended(T0)) for _ in range(5)]
    for _ in range(20):
        fleet.append(state=fleet.ended(T0))
    return LeaderboardCache(), fleet.snapshot(), inners


def test_a_scope_whose_outer_is_not_indexed_lists_its_inner_runs(loading):
    cache, snap, inners = loading
    page = cache.page(snap, {}, scope=OUTER, limit=50)
    assert sorted(row["verstr"] for row in page["rows"]) == sorted(inners)
    assert page["total"] == len(inners)


def test_its_facets_count_the_inner_runs(loading):
    cache, snap, inners = loading
    assert cache.facets_payload(snap, scope=OUTER)["total"] == len(inners)


def test_a_scope_nothing_names_is_still_unknown(loading):
    cache, snap, _ = loading
    with pytest.raises(UnknownScope):
        cache.page(snap, {}, scope="1.0.0-dev.nothing", limit=50)
