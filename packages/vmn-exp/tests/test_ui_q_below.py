"""The board's own ``q`` reads ``running_below``/``stuck_below``/``live_below``
like its ``top_q``: from the cached job rollups (no recount over the rows),
and a run deep in a tree moving re-judges the rows above it."""
import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(7)
    launch = fleet.append(state=finished(1))
    fleet.append(parent=launch, state=finished(1))
    fleet.append(parent=launch, state=running(T0))
    hung = fleet.append(state=finished(0))
    date = fleet.append(parent=hung, state=running(T0))
    fleet.append(parent=date, state=running(T0, age=3600))
    done = fleet.append(state=finished(0))
    fleet.append(parent=done, state=finished(0))
    return fleet, (launch, hung, date, done), LeaderboardCache()


def _kept(cache, snap, query, **params):
    page = cache.page(snap, SCHEMA, limit=100, query=query, **params)
    return {r["verstr"] for r in page["rows"]}


def test_q_running_below_keeps_the_outer_runs_with_running_descendants(board):
    fleet, (launch, hung, date, done), cache = board
    snap = fleet.snapshot()
    assert _kept(cache, snap, "running_below > 0") == {launch, hung}
    assert _kept(cache, snap, "stuck_below > 0") == {hung, date}
    assert _kept(cache, snap, "live_below > 0", top=True) == {launch, hung}


def test_q_below_reads_the_cached_rollups(board, monkeypatch):
    import vmn_exp.core.query_below as query_below

    fleet, (launch, hung, *_), cache = board
    monkeypatch.setattr(query_below, "below_counts", lambda rows: pytest.fail("recounted"))
    assert _kept(cache, fleet.snapshot(), "running_below > 0") == {launch, hung}


def test_q_below_follows_a_deep_run_of_a_new_generation(board):
    fleet, (launch, hung, date, done), cache = board
    assert _kept(cache, fleet.snapshot(), "stuck_below > 0") == {hung, date}
    fleet.set_state(fleet.index(date) + 1, finished(0))
    assert _kept(cache, fleet.snapshot(), "stuck_below > 0") == set()
