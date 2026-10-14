"""Plan 23 S3 bench: at 100k runs = 20 jobs x 5000 inners (4000 live), a
job's summary and failures answer a poll's ETag in microseconds and are
built within budget, and the run detail of a 5000-run job no longer reads
its subtree. Timed, so serial."""
import statistics
import time

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.readers.experiment_detail import status_detail

from vmn_exp.core import status as status_mod

JOBS, INNERS, LIVE = 20, 5000, 4000
SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _p95(samples):
    return statistics.quantiles(samples, n=20)[-1]


def _ms(seconds):
    return round(seconds * 1000, 2)


@pytest.fixture(scope="module")
def fleet():
    fleet = Fleet(23)
    fleet.seed_jobs(JOBS, INNERS, T0, live=LIVE)
    return fleet


@pytest.fixture
def warm(monkeypatch, fleet):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    cache.page(snap, SCHEMA, sort="loss", limit=50)
    cache.job_rollups(snap, SCHEMA)  # the Jobs view warmed the rollups
    return JobViews(cache), snap, [spec["verstr"] for spec in fleet.specs[:JOBS]]


def _poll(views, snap, job, route):
    """What a 304 costs: is it a job, and its ETag."""
    return views.is_job(snap, job) and views.etag(snap, SCHEMA, job, route=route)


@pytest.mark.serial
@pytest.mark.parametrize("route, built_budget", [("summary", 0.020), ("failures", 0.050)])
def test_job_answers_are_cheap_built_and_free_warm(warm, route, built_budget):
    views, snap, jobs = warm
    answer = views.summary if route == "summary" else views.failures
    built = [_timed(lambda job=job: answer(snap, SCHEMA, job)) for job in jobs]
    warm_answer = [_timed(lambda job=job: answer(snap, SCHEMA, job)) for job in jobs * 5]
    polls = [_timed(lambda job=job: _poll(views, snap, job, route)) for job in jobs * 10]
    print(f"\n{route}: built p95 {_ms(_p95(built))} ms (max {_ms(max(built))}), "
          f"warm p95 {_ms(_p95(warm_answer))} ms, 304 path p95 {_ms(_p95(polls))} ms")
    assert _p95(polls) <= 0.005, polls
    assert _p95(warm_answer) <= 0.005, warm_answer
    assert _p95(built) <= built_budget, built


def _detail(snap, job, job_status=None):
    return status_detail(
        None, "app", job, {}, [], lambda storage, app_name: snap.edges,
        read_run_state=lambda storage, app_name, v: snap.run_states.get(v),
        read_observed_at=lambda storage, app_name, v: None,
        read_child_row=snap.row, job_status=job_status,
    )


@pytest.mark.serial
def test_the_detail_of_a_5000_run_job_reads_the_rollup(warm):
    views, snap, jobs = warm
    from_rollup = lambda v: views.detail_status(snap, SCHEMA, v)  # noqa: E731
    before = statistics.median(_timed(lambda: _detail(snap, jobs[0])) for _ in range(5))
    first = _timed(lambda: _detail(snap, jobs[1], from_rollup))
    after = [_timed(lambda job=job: _detail(snap, job, from_rollup)) for job in jobs * 3]
    print(f"\ndetail of a 5000-run job: subtree walk {_ms(before)} ms; "
          f"from the rollup first {_ms(first)} ms, p95 {_ms(_p95(after))} ms")
    assert first <= 0.030 and _p95(after) <= 0.030, (first, after)
    assert _detail(snap, jobs[0], from_rollup)["fleet"]["counts"] == _detail(
        snap, jobs[0])["fleet"]["counts"]
