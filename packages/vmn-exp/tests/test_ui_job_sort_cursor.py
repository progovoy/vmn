"""A ``job:*`` order's keyset pages (plan 23 S6) follow :func:`job_sorted`
exactly: ties keep the default order, runs without the value come last."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_jobs import job_sorted

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture
def board(monkeypatch):
    """Jobs tied on their size (3 of 4 children, 2 of 2) and single runs,
    which have no job summary at all."""
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(11)
    for inners in (4, 2, 4, 2, 4):
        fleet.seed_jobs(1, inners, T0)
    for _ in range(5):
        fleet.append(state=fleet.ended(T0))
    return fleet.snapshot(), LeaderboardCache()


def _paged(cache, snap, limit, **params):
    got, cursor = [], None
    while True:
        page = cache.page(snap, SCHEMA, limit=limit, cursor=cursor, top=True, **params)
        got += [row["verstr"] for row in page["rows"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return got


@pytest.mark.parametrize("sort", ["job:total", "job:best", "job:progress"])
@pytest.mark.parametrize("order", [None, "asc", "desc"])
@pytest.mark.parametrize("limit", [1, 2, 3])
def test_cursor_pages_match_job_sorted_with_ties_and_missing_values(board, sort, order, limit):
    snap, cache = board
    default = cache.page(snap, SCHEMA, limit=10**6, top=True)["rows"]
    want = [row["verstr"] for row in job_sorted(
        default, cache.job_rollups(snap, SCHEMA), sort, order, SCHEMA)]
    assert len(want) == 10

    assert _paged(cache, snap, limit, sort=sort, order=order) == want
