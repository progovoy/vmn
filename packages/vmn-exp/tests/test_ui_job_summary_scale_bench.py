"""The outer run page's first requests at production scale (46k runs, one
outer run of 27k inner runs): its summary and its scoped first page answer
well within a second off a warm board base, and while a store's cold load
publishes a generation per chunk of records the summary's rollups move on
by each chunk's delta instead of being rebuilt. Timed, so serial."""
import time

import pytest
from bench_timing import fastest, fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui import job_rollup
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_delta import MAX_DELTA_SHARE


INNERS, SINGLES, LIVE = 27_000, 19_000, 50
CHUNK = 500  # records a cold load publishes at a time (core/index.py _REMOTE_CHUNK)
CHUNKS = 40
FIRST_BUDGETS = {"first": 1.0, "again": 0.005}  # summary + page + facets; repeat
CHUNK_SEC = 0.25


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


@pytest.fixture
def frozen():
    return FakeClock(T0)


@pytest.mark.serial
def test_a_27k_run_outer_summary_and_first_page_answer_within_a_second(frozen):
    fleet = Fleet(5)
    job = fleet.seed_jobs(1, INNERS, T0, live=LIVE)[0]
    for _ in range(SINGLES):
        fleet.append(state=fleet.ended(T0))
    snap = fleet.snapshot()

    def first_requests():
        """From a fresh board warmed by the refresher: ``{step: seconds}``."""
        cache = LeaderboardCache(now=frozen.now)
        views = JobViews(cache)
        took = {"base": _timed(lambda: cache.warm(snap))}  # off the request path
        took["summary"] = _timed(lambda: views.summary(snap, {}, job))
        took["page"] = _timed(lambda: cache.page(snap, {}, scope=job, limit=50))
        took["facets"] = _timed(lambda: cache.facets_payload(snap, scope=job))
        took["again"] = _timed(lambda: views.summary(snap, {}, job))
        took["first"] = took["summary"] + took["page"] + took["facets"]
        return took

    took = fastest_each(first_requests, FIRST_BUDGETS)
    summary, page, facets = took["summary"], took["page"], took["facets"]
    print(f"\nbase {took['base'] * 1000:.0f} ms; summary {summary * 1000:.0f} ms, "
          f"scoped page {page * 1000:.0f} ms, scoped facets {facets * 1000:.0f} ms, "
          f"summary again {took['again'] * 1000:.2f} ms")
    assert took["first"] <= FIRST_BUDGETS["first"], (summary, page, facets)
    assert took["again"] <= FIRST_BUDGETS["again"], took["again"]


@pytest.mark.serial
def test_loading_chunks_move_the_rollups_on_instead_of_rebuilding(frozen, monkeypatch):
    builds = []
    build = job_rollup.StaticRollups.build.__func__
    monkeypatch.setattr(job_rollup.StaticRollups, "build", classmethod(
        lambda cls, base, spec: builds.append(len(base.rows)) or build(cls, base, spec)))
    runs = []

    def load():
        """A fresh store's cold load, chunk by chunk: the slowest chunk's summary."""
        builds.clear()
        fleet = Fleet(6)
        job = fleet.append(state=None)
        cache = LeaderboardCache(now=frozen.now)
        views = JobViews(cache)
        times = []
        for _ in range(CHUNKS):
            for _ in range(CHUNK * 3 // 5):
                fleet.append(parent=job, state=fleet.ended(T0))
            for _ in range(CHUNK * 2 // 5):
                fleet.append(state=fleet.ended(T0))
            snap = fleet.snapshot()
            cache.warm(snap)
            times.append(_timed(lambda snap=snap: views.summary(snap, {}, job)))
        runs.append(times)
        return max(times)

    slowest = fastest(load, CHUNK_SEC)
    times = runs[-1]
    print(f"\nper-chunk summary ms {[round(t * 1000, 1) for t in times]} (slowest uncontended "
          f"{slowest * 1000:.1f}); rebuilt at rows {builds}")
    # Only while a chunk (plus the outer run's own row) is above the delta
    # share of the rows is a rebuild cheaper: the first ~10 chunks.
    assert max(builds) <= (CHUNK + 1) / MAX_DELTA_SHARE, builds
    assert slowest <= CHUNK_SEC, times
