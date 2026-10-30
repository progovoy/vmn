"""``running_below`` and ``stuck_below``: a top-level row's runs below it
running or stuck (its rollup's counts), readable by ``top_query`` like
``live_below`` — so the outer runs' status chips match an outer run whose
own status and ``tree_status`` read ``failed`` while its runs still run."""
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
    return fleet, (launch, hung, done), LeaderboardCache()


def _top(cache, snap, top_query):
    page = cache.page(snap, SCHEMA, limit=100, top=True, top_query=top_query)
    return {r["verstr"] for r in page["rows"]}


def test_running_below_keeps_a_failed_launch_with_a_running_run(board):
    fleet, (launch, hung, done), cache = board
    snap = fleet.snapshot()
    assert _top(cache, snap, 'status = "running"') == set()
    assert _top(cache, snap, "running_below > 0") == {launch, hung}


def test_stuck_below_keeps_a_tree_with_a_stuck_run(board):
    fleet, (launch, hung, done), cache = board
    assert _top(cache, fleet.snapshot(), "stuck_below > 0") == {hung}


def test_status_below_follows_a_new_generation(board):
    fleet, (launch, hung, done), cache = board
    assert launch in _top(cache, fleet.snapshot(), "running_below > 0")
    fleet.set_state(fleet.index(launch) + 2, finished(0))
    assert _top(cache, fleet.snapshot(), "running_below > 0") == {hung}
