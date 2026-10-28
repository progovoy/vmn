"""Plan 28 §4.5: the Live/Review presets' filter, ``top_query`` (``top_q=``
over HTTP): a query the top-level rows pass by their own fields, beside
``q``, so a Jobs view search matching subtrees (``match_subtree``) keeps
the preset on the outer runs themselves."""
import pytest
from leaderboard_fleet import T0, Fleet, finished
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}
NEEDLE = 'verstr ~ "needle"'
OUTERS = 'kind = "outer"'


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(5)
    jobs = fleet.seed_jobs(3, 6, T0, live=2)
    hits = [fleet.append(parent=job, state=fleet.ended(T0), verstr=f"1.0.0-dev.needle{i}")
            for i, job in enumerate(jobs[:2])]
    single = fleet.append(state=fleet.ended(T0), verstr="1.0.0-dev.needle-single")
    return fleet, jobs, hits, single, LeaderboardCache()


def _verstrs(page):
    return {r["verstr"] for r in page["rows"]}


def _page(cache, snap, **params):
    return cache.page(snap, SCHEMA, limit=100, top=True, **params)


def test_top_query_filters_the_top_rows(board):
    fleet, jobs, hits, single, cache = board
    page = _page(cache, fleet.snapshot(), top_query=OUTERS)
    assert _verstrs(page) == set(jobs)
    assert all(r["job"] for r in page["rows"])


def test_with_match_subtree_q_matches_subtrees_and_top_query_the_top_rows(board):
    fleet, jobs, hits, single, cache = board
    page = _page(cache, fleet.snapshot(), query=NEEDLE, match_subtree=True, top_query=OUTERS)
    assert _verstrs(page) == set(jobs[:2])
    assert page["jobs_matched"] == 2


def test_top_query_and_q_are_both_applied(board):
    fleet, jobs, hits, single, cache = board
    page = _page(cache, fleet.snapshot(), query=f'verstr != "{jobs[0]}"', top_query=OUTERS)
    assert _verstrs(page) == set(jobs[1:])


def test_a_new_generation_moves_a_top_query_order(board):
    fleet, jobs, hits, single, cache = board
    live = 'status in ("running", "stuck")'
    assert _verstrs(_page(cache, fleet.snapshot(), top_query=live)) == set(jobs)
    fleet.set_state(fleet.index(jobs[0]), finished())
    assert _verstrs(_page(cache, fleet.snapshot(), top_query=live)) == set(jobs[1:])


def test_grouped_top_query_groups_the_passing_top_rows(board):
    fleet, jobs, hits, single, cache = board
    body = cache.groups(fleet.snapshot(), SCHEMA, "status", top=True, top_query=OUTERS)
    rows = {r["verstr"] for g in body["groups"] for r in g["rows"]}
    assert rows == set(jobs)


def test_top_query_without_top_is_refused(board):
    fleet, *_, cache = board
    with pytest.raises(ValueError):
        cache.page(fleet.snapshot(), SCHEMA, limit=10, top_query=OUTERS)
