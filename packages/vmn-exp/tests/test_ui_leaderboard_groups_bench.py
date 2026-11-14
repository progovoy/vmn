"""Plan 22 K2 bench: at 100k runs a grouped page answers in the same order of
time as an ungrouped one — cold, warm, and on the first request after a new
index generation (moved on by deltas, not rebuilt). Timed, so serial."""
import statistics
import time

import pytest
from bench_timing import fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
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
def test_a_grouped_page_costs_about_what_a_flat_page_costs(fleet, group, slack):
    passes = []
    # Each step is how far the grouped page went past what its check allows:
    # within its budget is the check holding.
    budgets = {"cold": slack, "next": slack, "warm": 0.0, "warm_floor": 0.005}
    took = fastest_each(lambda: _pass(fleet, group, passes), budgets)
    (grouped_cold, flat_cold), (grouped_warm, flat_warm), nexts = passes[-1]
    print(f"\n{group}: uncontended excess {took}")
    assert took["cold"] < slack, (grouped_cold, flat_cold)
    assert took["warm"] < 0 or took["warm_floor"] < 0.005, (grouped_warm, flat_warm)
    assert took["next"] < slack, nexts


def _pass(fleet, group, passes):
    """A fresh cache on the fleet as it is, cold, warm and over GENERATIONS
    new generations; the pass's times appended to *passes*."""
    cache = LeaderboardCache(now=FakeClock(T0).now)
    snap = fleet.snapshot()
    flat = lambda: cache.page(snap, SCHEMA, sort="loss", limit=50)  # noqa: E731
    grouped = lambda: cache.groups(snap, SCHEMA, group, sort="loss", limit=50)  # noqa: E731

    flat_cold = _timed(flat)  # builds the base the grouping shares
    grouped_cold = _timed(grouped)
    flat_warm, grouped_warm = _warm(flat), _warm(grouped)

    nexts = []
    for _ in range(GENERATIONS):
        fleet.mutate(T0, 20, reparent=False)
        snap = fleet.snapshot()
        flat_next, grouped_next = _timed(flat), _timed(grouped)
        nexts.append((grouped_next, flat_next))
    passes.append(((grouped_cold, flat_cold), (grouped_warm, flat_warm), nexts))
    return {"cold": grouped_cold - flat_cold,
            "warm": grouped_warm - 10 * flat_warm, "warm_floor": grouped_warm,
            "next": max(grouped - 3 * flat for grouped, flat in nexts)}
