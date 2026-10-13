"""Plan 23 B0/S1 bench: at 100k runs = 20 jobs x 5000 inners (4000 live), a
job's rollup is a memo hit warm, every job's summary too, and a new index
generation of 500 changed runs moves the rollups on for about what the flat
page pays for the same generation. Timed, so serial."""
import statistics
import time

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

JOBS, INNERS, LIVE = 20, 5000, 4000
SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}
GENERATIONS, CHANGED = 3, 500


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _p95(samples):
    return statistics.quantiles(samples, n=20)[-1]


@pytest.fixture(scope="module")
def fleet():
    fleet = Fleet(23)
    fleet.seed_jobs(JOBS, INNERS, T0, live=LIVE)
    return fleet


@pytest.mark.serial
def test_job_rollups_are_o1_warm_and_cheap_per_generation(monkeypatch, fleet):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    jobs = [spec["verstr"] for spec in fleet.specs[:JOBS]]
    flat = lambda: cache.page(snap, SCHEMA, sort="loss", limit=50)  # noqa: E731
    rollups = lambda: cache.job_rollups(snap, SCHEMA)  # noqa: E731

    flat_cold = _timed(flat)
    rollups_cold = _timed(rollups)
    one_cold = _timed(lambda: cache.job_rollup(snap, SCHEMA, jobs[0]))
    for job in jobs:
        cache.job_rollup(snap, SCHEMA, job)
    warm_one = [_timed(lambda job=job: cache.job_rollup(snap, SCHEMA, job)) for job in jobs * 10]
    warm_all = statistics.median(_timed(rollups) for _ in range(7))
    assert _p95(warm_one) <= 0.005, warm_one
    assert warm_all <= 0.020, warm_all

    nexts = []
    for _ in range(GENERATIONS):
        fleet.mutate(T0, CHANGED, reparent=False)
        snap = fleet.snapshot()
        flat_next = _timed(flat)  # derives the base the rollups share
        rollup_next = _timed(lambda snap=snap: (rollups(), cache.job_rollup(snap, SCHEMA, jobs[0])))
        nexts.append((round(rollup_next * 1000, 1), round(flat_next * 1000, 1)))
        assert rollup_next <= 2 * flat_next, (rollup_next, flat_next)
    print(f"\nflat cold {flat_cold * 1000:.0f} ms, rollups cold {rollups_cold * 1000:.0f} ms, "
          f"one job cold {one_cold * 1000:.1f} ms; warm one p95 {_p95(warm_one) * 1000:.3f} ms, "
          f"warm all {warm_all * 1000:.3f} ms; next generation (rollup ms, flat ms) {nexts}")
