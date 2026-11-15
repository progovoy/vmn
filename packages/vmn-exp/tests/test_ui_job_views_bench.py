"""Plan 23 S3 bench: at 100k runs = 20 jobs x 5000 inners (4000 live), a
job's summary and failures answer a poll's ETag in microseconds and are
built within budget, and the run detail of a 5000-run job no longer reads
its subtree. Timed, so serial."""
import statistics
import time

import pytest
from bench_timing import fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.readers.experiment_detail import status_detail


JOBS, INNERS, LIVE = 20, 5000, 4000
SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}
WARM_SEC = 0.005  # a warm answer, and the 304 path
DETAIL_SEC = 0.030


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


def _warmed(fleet):
    """A fresh board the Jobs view warmed: ``(views, snap, jobs)``."""
    cache, snap = LeaderboardCache(now=FakeClock(T0).now), fleet.snapshot()
    cache.page(snap, SCHEMA, sort="loss", limit=50)
    cache.job_rollups(snap, SCHEMA)  # the Jobs view warmed the rollups
    return JobViews(cache), snap, [spec["verstr"] for spec in fleet.specs[:JOBS]]


def _poll(views, snap, job, route):
    """What a 304 costs: is it a job, and its ETag."""
    return views.is_job(snap, job) and views.etag(snap, SCHEMA, job, route=route)


@pytest.mark.serial
@pytest.mark.parametrize("route, built_budget", [("summary", 0.020), ("failures", 0.050)])
def test_job_answers_are_cheap_built_and_free_warm(fleet, route, built_budget):
    samples = {}

    def answers():
        """p95s from a freshly warmed board: ``{step: seconds}``."""
        views, snap, jobs = _warmed(fleet)
        answer = views.summary if route == "summary" else views.failures
        samples["built"] = [_timed(lambda job=job: answer(snap, SCHEMA, job)) for job in jobs]
        samples["warm"] = [_timed(lambda job=job: answer(snap, SCHEMA, job)) for job in jobs * 5]
        samples["polls"] = [_timed(lambda job=job: _poll(views, snap, job, route))
                            for job in jobs * 10]
        took = {step: _p95(times) for step, times in samples.items()}
        took["built_max"] = max(samples["built"])
        return took

    budgets = {"polls": WARM_SEC, "warm": WARM_SEC, "built": built_budget}
    took = fastest_each(answers, budgets)
    print(f"\n{route}: built p95 {_ms(took['built'])} ms (max {_ms(took['built_max'])}), "
          f"warm p95 {_ms(took['warm'])} ms, 304 path p95 {_ms(took['polls'])} ms")
    for step, budget in budgets.items():
        assert took[step] <= budget, samples[step]


def _detail(snap, job, job_status=None):
    return status_detail(
        None, "app", job, {}, [], lambda storage, app_name: snap.edges,
        read_run_state=lambda storage, app_name, v: snap.run_states.get(v),
        read_observed_at=lambda storage, app_name, v: None,
        read_child_row=snap.row, job_status=job_status, now=T0,
    )


@pytest.mark.serial
def test_the_detail_of_a_5000_run_job_reads_the_rollup(fleet):
    snap, jobs = fleet.snapshot(), [spec["verstr"] for spec in fleet.specs[:JOBS]]
    before = statistics.median(_timed(lambda: _detail(snap, jobs[0])) for _ in range(5))
    attempts = []

    def from_rollups():
        """Details off a freshly warmed board's rollups: ``{step: seconds}``."""
        views, snap, jobs = _warmed(fleet)
        from_rollup = lambda v: views.detail_status(snap, SCHEMA, v)  # noqa: E731
        first = _timed(lambda: _detail(snap, jobs[1], from_rollup))
        after = [_timed(lambda job=job: _detail(snap, job, from_rollup)) for job in jobs * 3]
        attempts.append((snap, from_rollup, after))
        return {"first": first, "after": _p95(after)}

    took = fastest_each(from_rollups, {"first": DETAIL_SEC, "after": DETAIL_SEC})
    snap, from_rollup, after = attempts[-1]
    print(f"\ndetail of a 5000-run job: subtree walk {_ms(before)} ms; "
          f"from the rollup first {_ms(took['first'])} ms, p95 {_ms(took['after'])} ms")
    assert took["first"] <= DETAIL_SEC and took["after"] <= DETAIL_SEC, (took["first"], after)
    assert _detail(snap, jobs[0], from_rollup)["fleet"]["counts"] == _detail(
        snap, jobs[0])["fleet"]["counts"]
