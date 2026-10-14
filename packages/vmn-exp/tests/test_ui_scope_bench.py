"""Plan 23 S2 bench: at 100k runs = 20 jobs x 5000 inners (4000 live), the
Jobs view page (``top=1``, 50 rows, ``job:failed_pct``) and a scoped page
(one job, 200 rows, by a metric) are memo hits warm, scoped facets are
cheap, and a new index generation of 500 changed runs moves a scoped page
on for about what the flat page pays. Timed, so serial."""
import statistics
import time

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

JOBS, INNERS, LIVE = 20, 5000, 4000
SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}
GENERATIONS, CHANGED = 3, 500


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
def test_jobs_view_and_scoped_pages_are_cheap(monkeypatch, fleet):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    job = fleet.specs[3]["verstr"]
    flat = lambda: cache.page(snap, SCHEMA, sort="loss", limit=50)  # noqa: E731
    jobs = lambda: cache.page(snap, SCHEMA, top=True, sort="job:failed_pct", limit=50)  # noqa: E731
    scoped = lambda: cache.page(snap, SCHEMA, scope=job, sort="loss", limit=200)  # noqa: E731
    facets = lambda: cache.facets(snap, scope=job, status="succeeded")  # noqa: E731

    cold = {name: _ms(_timed(fn)) for name, fn in
            [("flat", flat), ("jobs", jobs), ("scoped", scoped), ("facets", facets)]}
    warm = {name: [_timed(fn) for _ in range(40)] for name, fn in
            [("jobs", jobs), ("scoped", scoped), ("facets", facets)]}
    assert _p95(warm["jobs"]) <= 0.050, warm["jobs"]
    assert _p95(warm["scoped"]) <= 0.080, warm["scoped"]
    assert _p95(warm["facets"]) <= 0.100, warm["facets"]
    assert cold["facets"] <= 100, cold

    nexts = []
    for _ in range(GENERATIONS):
        fleet.mutate(T0, CHANGED, reparent=False)
        snap = fleet.snapshot()
        flat_next = _timed(flat)  # derives the base the others share
        scoped_next = _timed(scoped)
        jobs_next = _timed(jobs)
        nexts.append((_ms(scoped_next), _ms(jobs_next), _ms(flat_next)))
        assert scoped_next <= 3 * flat_next, (scoped_next, flat_next)
    print(f"\ncold ms {cold}; warm p95 ms "
          f"{ {name: round(_p95(s) * 1000, 3) for name, s in warm.items()} }; "
          f"next generation (scoped ms, jobs ms, flat ms) {nexts}")
