"""The solo user's first screen (plan 43 F13): a store of 0, 1 or a dozen
plain runs counts no outer runs, so the web app opens on the runs board
(plan 38 A6), and that board's page lists every run with its primary metric."""
import pytest
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

CLOCK = FakeClock(start=T0)
SCHEMA = {"loss": {"goal": "min", "primary": True}}
SIZES = [0, 1, 12]


def _solo_store(size):
    fleet = Fleet(7)
    for i in range(size):
        fleet.append(state=fleet.ended(T0, code=0))
        fleet.edit(i, values={"loss": 1.0 / (i + 1)})
    return fleet.snapshot()


@pytest.mark.parametrize("size", SIZES)
def test_a_store_of_single_runs_counts_no_outer_runs(size):
    cache = LeaderboardCache(now=CLOCK.now)
    assert cache.top_counts(_solo_store(size)) == {"jobs": 0, "singles": size}


@pytest.mark.parametrize("size", SIZES)
def test_the_runs_board_lists_every_single_run_with_its_primary_metric(size):
    snap = _solo_store(size)
    page = LeaderboardCache(now=CLOCK.now).page(snap, SCHEMA, limit=100, top="singles")
    assert page["total"] == size
    assert {row["verstr"] for row in page["rows"]} == {row["verstr"] for row in snap.rows}
    assert all(row["metrics"]["loss"] == 1.0 / row["idx"] for row in page["rows"])
