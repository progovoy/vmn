"""Plan 22 K2 bench: at 100k runs a grouped page answers in the same order of
time as an ungrouped one — cold, warm, and on the first request after a new
index generation (moved on by deltas, not rebuilt). Timed, so serial."""
import statistics
import time

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

N = 100_000
SCHEMA = {"loss": {"goal": "min"}}
GENERATIONS = 3


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _warm(fn, repeat=7):
    return statistics.median(_timed(fn) for _ in range(repeat))


@pytest.fixture(scope="module")
def fleet():
    fleet = Fleet(7)
    fleet.seed(N, T0, sweeps=50, live=40)
    return fleet


@pytest.mark.serial
# parent: 50 sweeps among single runs; code_verstr: a group per run;
# status: a few groups of tens of thousands of rows each.
@pytest.mark.parametrize("group,slack", [("parent", 0.05), ("code_verstr", 0.3), ("status", 0.05)])
def test_a_grouped_page_costs_about_what_a_flat_page_costs(monkeypatch, fleet, group, slack):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache = LeaderboardCache()
    snap = fleet.snapshot()
    flat = lambda: cache.page(snap, SCHEMA, sort="loss", limit=50)  # noqa: E731
    grouped = lambda: cache.groups(snap, SCHEMA, group, sort="loss", limit=50)  # noqa: E731

    flat_cold = _timed(flat)  # builds the base the grouping shares
    grouped_cold = _timed(grouped)
    assert grouped_cold < flat_cold + slack, (grouped_cold, flat_cold)
    flat_warm, grouped_warm = _warm(flat), _warm(grouped)
    assert grouped_warm < max(10 * flat_warm, 0.005), (grouped_warm, flat_warm)

    for _ in range(GENERATIONS):
        fleet.mutate(T0, 20, reparent=False)
        snap = fleet.snapshot()
        flat_next, grouped_next = _timed(flat), _timed(grouped)
        assert grouped_next < 3 * flat_next + slack, (grouped_next, flat_next)
