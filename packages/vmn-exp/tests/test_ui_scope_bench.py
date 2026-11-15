"""Plan 23 S2 bench: at 100k runs = 20 jobs x 5000 inners (4000 live), the
Jobs view page (``top=1``, 50 rows, ``job:failed_pct``) and a scoped page
(one job, 200 rows, by a metric) are memo hits warm, scoped facets are
cheap, and a new index generation of 500 changed runs moves a scoped page
on for about what the flat page pays. Timed, so serial."""
import statistics
import time

import pytest
from bench_timing import fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


JOBS, INNERS, LIVE = 20, 5000, 4000
SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}
GENERATIONS, CHANGED = 3, 500
# p95 of the warm pages, the cold scoped facets, and how far a next
# generation's scoped page went past 3x the flat page's.
BUDGETS = {"jobs": 0.050, "scoped": 0.080, "facets": 0.100, "facets_cold": 0.100, "next": 0.0}


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _p95(samples):
    return statistics.quantiles(samples, n=20)[-1]


def _ms(seconds):
    return round(seconds * 1000, 1)


@pytest.fixture(scope="module")
def fleet():
    fleet = Fleet(23)
    fleet.seed_jobs(JOBS, INNERS, T0, live=LIVE)
    return fleet


@pytest.mark.serial
def test_jobs_view_and_scoped_pages_are_cheap(fleet):
    passes = []
    took = fastest_each(lambda: _pass(fleet, passes), BUDGETS)
    cold, warm, nexts = passes[-1]
    print(f"\ncold ms {cold}; warm p95 ms "
          f"{ {name: round(_p95(s) * 1000, 3) for name, s in warm.items()} }; "
          f"next generation (scoped ms, jobs ms, flat ms) {nexts}; "
          f"uncontended {took}")
    assert took["jobs"] <= BUDGETS["jobs"], warm["jobs"]
    assert took["scoped"] <= BUDGETS["scoped"], warm["scoped"]
    assert took["facets"] <= BUDGETS["facets"], warm["facets"]
    assert took["facets_cold"] <= BUDGETS["facets_cold"], cold
    assert took["next"] <= BUDGETS["next"], nexts


def _pass(fleet, passes):
    """A fresh cache on the fleet as it is, cold, warm and over GENERATIONS
    new generations; the pass's times appended to *passes*."""
    cache, snap = LeaderboardCache(now=FakeClock(T0).now), fleet.snapshot()
    job = fleet.specs[3]["verstr"]
    flat = lambda: cache.page(snap, SCHEMA, sort="loss", limit=50)  # noqa: E731
    jobs = lambda: cache.page(snap, SCHEMA, top=True, sort="job:failed_pct", limit=50)  # noqa: E731
    scoped = lambda: cache.page(snap, SCHEMA, scope=job, sort="loss", limit=200)  # noqa: E731
    facets = lambda: cache.facets(snap, scope=job, status="succeeded")  # noqa: E731

    cold = {name: _timed(fn) for name, fn in
            [("flat", flat), ("jobs", jobs), ("scoped", scoped), ("facets", facets)]}
    warm = {name: [_timed(fn) for _ in range(40)] for name, fn in
            [("jobs", jobs), ("scoped", scoped), ("facets", facets)]}

    nexts, excess = [], []
    for _ in range(GENERATIONS):
        fleet.mutate(T0, CHANGED, reparent=False)
        snap = fleet.snapshot()
        flat_next = _timed(flat)  # derives the base the others share
        scoped_next = _timed(scoped)
        jobs_next = _timed(jobs)
        nexts.append((_ms(scoped_next), _ms(jobs_next), _ms(flat_next)))
        excess.append(scoped_next - 3 * flat_next)
    passes.append(({name: _ms(t) for name, t in cold.items()}, warm, nexts))
    return {**{name: _p95(s) for name, s in warm.items()},
            "facets_cold": cold["facets"], "next": max(excess)}
