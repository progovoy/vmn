"""Plan 23 S7 bench: the grouped Jobs view (``top=jobs``, ``group=branch``)
at 100k runs (20 jobs x 5000) answers warm in <= 20 ms. Timed, so serial."""
import statistics
import time

import pytest
from bench_timing import fastest
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


SCHEMA = {"loss": {"goal": "min", "primary": True}}
WARM_SEC = 0.020


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


@pytest.mark.serial
def test_a_grouped_jobs_view_at_100k_runs():
    fleet = Fleet(4)
    fleet.seed_jobs(20, 5000, T0, live=40)
    cache, snap = LeaderboardCache(now=FakeClock(T0).now), fleet.snapshot()
    grouped = lambda: cache.groups(snap, SCHEMA, "branch", top="jobs")  # noqa: E731
    cold = _timed(grouped)
    warm = fastest(lambda: statistics.median(_timed(grouped) for _ in range(7)), WARM_SEC)
    print(f"\ngrouped jobs view at 100k: cold {cold * 1000:.0f} ms, warm {warm * 1000:.2f} ms")
    assert warm <= WARM_SEC, warm
