"""The outer run page's first requests at production scale (46k runs, one
outer run of 27k inner runs): its summary and its scoped first page answer
well within a second off a warm board base, and while a store's cold load
publishes a generation per chunk of records the summary's rollups move on
by each chunk's delta instead of being rebuilt. Timed, so serial."""
import time

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui import job_rollup
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_delta import MAX_DELTA_SHARE

from vmn_exp.core import status as status_mod

INNERS, SINGLES, LIVE = 27_000, 19_000, 50
CHUNK = 500  # records a cold load publishes at a time (core/index.py _REMOTE_CHUNK)
CHUNKS = 40


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


@pytest.mark.serial
def test_a_27k_run_outer_summary_and_first_page_answer_within_a_second(frozen):
    fleet = Fleet(5)
    job = fleet.seed_jobs(1, INNERS, T0, live=LIVE)[0]
    for _ in range(SINGLES):
        fleet.append(state=fleet.ended(T0))
    snap = fleet.snapshot()
    cache = LeaderboardCache()
    views = JobViews(cache)
    base = _timed(lambda: cache.warm(snap))  # the refresher, off the request path
    summary = _timed(lambda: views.summary(snap, {}, job))
    page = _timed(lambda: cache.page(snap, {}, scope=job, limit=50))
    facets = _timed(lambda: cache.facets_payload(snap, scope=job))
    again = _timed(lambda: views.summary(snap, {}, job))
    print(f"\nbase {base * 1000:.0f} ms; summary {summary * 1000:.0f} ms, "
          f"scoped page {page * 1000:.0f} ms, scoped facets {facets * 1000:.0f} ms, "
          f"summary again {again * 1000:.2f} ms")
    assert summary + page + facets <= 1.0, (summary, page, facets)
    assert again <= 0.005, again


@pytest.mark.serial
def test_loading_chunks_move_the_rollups_on_instead_of_rebuilding(frozen, monkeypatch):
    builds = []
    build = job_rollup.StaticRollups.build.__func__
    monkeypatch.setattr(job_rollup.StaticRollups, "build", classmethod(
        lambda cls, base, spec: builds.append(len(base.rows)) or build(cls, base, spec)))
    fleet = Fleet(6)
    job = fleet.append(state=None)
    cache = LeaderboardCache()
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
    print(f"\nper-chunk summary ms {[round(t * 1000, 1) for t in times]}; rebuilt at rows {builds}")
    # Only while a chunk (plus the outer run's own row) is above the delta
    # share of the rows is a rebuild cheaper: the first ~10 chunks.
    assert max(builds) <= (CHUNK + 1) / MAX_DELTA_SHARE, builds
    assert max(times) <= 0.25, times
