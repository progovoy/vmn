"""Plan 23 cache layer: one memo per job answer (minute + live bucket), rows
patched at a bucket built once, a job's top 10 and failures read off the
scoped order and the rows' ``failure_sig``, and job importance not re-run
for every completion."""
import datetime

import pytest
from leaderboard_fleet import T0, Fleet, finished
from vmn_exp.core import status as status_mod
from vmn_exp.ui import job_failures, job_views, leaderboard_answers
from vmn_exp.ui.job_rollup_payload import failure_counts
from vmn_exp.ui.job_tally import RollupSpec, Tally
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min", "primary": True}}


def _at(monkeypatch, seconds):
    when = T0 + datetime.timedelta(seconds=seconds)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _idle_job(inners=40):
    """A finished job of *inners* finished runs: nothing live."""
    fleet = Fleet(51)
    (job,) = fleet.seed_jobs(1, inners, T0)
    fleet.set_state(fleet.index(job), finished())
    return fleet, job


def test_patched_rows_are_built_once_per_bucket(monkeypatch):
    _at(monkeypatch, 0)
    fleet = Fleet(50)
    fleet.seed_jobs(2, 30, T0, live=5)
    base, bucket = LeaderboardCache()._base(fleet.snapshot())
    patched = base.patched(bucket)
    assert patched is base.patched(bucket)
    assert patched == dict(zip(base.patch.changed, base.changed_at(bucket)))


def test_a_jobs_subtree_rows_come_from_the_memoized_scope(monkeypatch):
    _at(monkeypatch, 0)
    fleet, job = _idle_job()
    cache = LeaderboardCache()
    views, snap = JobViews(cache), fleet.snapshot()
    views.failures(snap, SCHEMA, job)
    assert job in cache._base(snap)[0].scopes


def test_rollups_and_summaries_are_one_answer_per_minute_while_nothing_is_live(monkeypatch):
    fleet, job = _idle_job()
    cache = LeaderboardCache()
    views, snap = JobViews(cache), fleet.snapshot()
    _at(monkeypatch, 5)
    rollups, summary = cache.job_rollups(snap, SCHEMA), views.summary(snap, SCHEMA, job)
    _at(monkeypatch, 25)
    assert cache.job_rollups(snap, SCHEMA) is rollups
    assert views.summary(snap, SCHEMA, job) is summary
    _at(monkeypatch, 65)
    assert cache.job_rollups(snap, SCHEMA) is not rollups


def test_failure_counts_read_only_the_parts():
    spec = RollupSpec({})
    rows = [{"verstr": "a", "status": "failed", "exit_code": 1,
             "metrics": {}, "parent": "j"}]
    assert failure_counts([Tally.of(rows, spec), Tally.of(rows, spec)]) == {"failed | exit=1": 2}


def test_the_summary_top_reads_a_slice_of_the_scoped_order(monkeypatch):
    _at(monkeypatch, 0)
    fleet, job = _idle_job(inners=200)
    seen = []
    real = job_views.top_rows

    def counted(rows, *args, **kw):
        rows = list(rows)
        seen.append(len(rows))
        return real(rows, *args, **kw)

    monkeypatch.setattr(job_views, "top_rows", counted)
    summary = JobViews(LeaderboardCache()).summary(fleet.snapshot(), SCHEMA, job)
    assert len(summary["top"]) == 10
    assert seen and max(seen) < 50


def test_failures_read_the_rows_failure_sig(monkeypatch):
    _at(monkeypatch, 0)
    fleet, job = _idle_job(inners=60)

    def recomputed(row):
        raise AssertionError("signature recomputed")

    monkeypatch.setattr(job_failures, "signature", recomputed)
    body = JobViews(LeaderboardCache()).failures(fleet.snapshot(), SCHEMA, job)
    assert body["total_failed"] == sum(c["count"] for c in body["clusters"]) > 0


def _scored_job(inners):
    fleet, job = _idle_job(inners)
    for i in range(1, inners + 1):
        fleet.edit(i, values={"loss": i / inners})
    return fleet, job


def test_job_importance_is_not_rerun_for_every_completion(monkeypatch):
    _at(monkeypatch, 0)
    fleet, job = _scored_job(100)
    calls = []
    real = leaderboard_answers.param_importance
    monkeypatch.setattr(leaderboard_answers, "param_importance",
                        lambda *a, **kw: calls.append(1) or real(*a, **kw))
    cache = LeaderboardCache()
    first = cache.importance(fleet.snapshot(), SCHEMA, "loss", scope=job)
    kid = fleet.append(parent=job, state=fleet.ended(T0, code=0))
    fleet.edit(fleet.index(kid), values={"loss": 0.33})
    assert cache.importance(fleet.snapshot(), SCHEMA, "loss", scope=job) == first
    assert len(calls) == 1
    for _ in range(10):
        kid = fleet.append(parent=job, state=fleet.ended(T0, code=0))
        fleet.edit(fleet.index(kid), values={"loss": 0.5})
    cache.importance(fleet.snapshot(), SCHEMA, "loss", scope=job)
    assert len(calls) == 2


pytest.importorskip("fastapi")
from test_ui_scope_route import BASE, served  # noqa: E402,F401


def test_a_jobs_view_poll_answers_304_within_the_minute(served, monkeypatch):  # noqa: F811
    client, _ = served
    url, params = f"{BASE}/experiments", {"top": "1", "limit": 5}
    _at(monkeypatch, 5)
    tag = client.get(url, params=params).headers["etag"]
    _at(monkeypatch, 25)
    again = client.get(url, params=params, headers={"If-None-Match": tag})
    assert again.status_code == 304
    _at(monkeypatch, 65)
    assert client.get(url, params=params).headers["etag"] != tag
