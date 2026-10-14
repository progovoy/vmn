"""Plan 23 S3: what a job's page reads — its summary (rollup + top 10 on the
main metric), its failure clusters and the run detail's fleet — answered
from the leaderboard cache, as a brute-force walk of the snapshot does."""
import datetime

import pytest
from job_rollup_reference import annotated, subtree
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.core.tree import children_by_parent
from vmn_exp.ui.failure_signature import signature
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _members(snap, job):
    rows = annotated(snap)
    by_verstr = {row["verstr"]: row for row in rows}
    return [by_verstr[v] for v in subtree(job, children_by_parent(rows))
            if v in by_verstr and not by_verstr[v].get("archived")]


def _want_top(members, descending=False):
    scored = [r for r in members if isinstance(r["metrics"].get("loss"), float)
              and r["metrics"]["loss"] == r["metrics"]["loss"]]
    scored.sort(key=lambda r: ((-1 if descending else 1) * r["metrics"]["loss"], r["verstr"]))
    return [{"verstr": r["verstr"], "idx": r["idx"], "name": r.get("name"),
             "status": r["status"], "value": r["metrics"]["loss"]} for r in scored[:10]]


def test_the_summary_is_the_rollup_with_the_job_row_and_its_top_ten():
    fleet = Fleet(31)
    jobs = fleet.seed_jobs(2, 60, T0, live=10)
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    summary = views.summary(snap, SCHEMA, jobs[0])
    rollup = views.cache.job_rollup(snap, SCHEMA, jobs[0])
    assert {k: summary[k] for k in rollup} == rollup
    assert summary["idx"] == 1 and summary["kind"] == "outer"
    assert summary["status"] == "running" and summary["sweep"] is False
    assert summary["tree_status"] in ("running", "failed", "stuck")
    assert summary["top"] == _want_top(_members(snap, jobs[0]))
    assert summary["top"][0]["verstr"] == rollup["metrics"]["loss"]["best_verstr"]


def test_top_follows_the_goal_and_moves_with_each_generation():
    fleet = Fleet(32)
    jobs = fleet.seed_jobs(3, 40, T0, live=8)
    views = JobViews(LeaderboardCache())
    schema = {"loss": {"goal": "max", "primary": True}}
    now = T0
    for _ in range(6):
        snap = fleet.snapshot()
        for job in jobs:
            assert views.summary(snap, schema, job)["top"] == _want_top(
                _members(snap, job), descending=True)
        now += datetime.timedelta(seconds=40)
        fleet.mutate(now, 6, reparent=False)


def test_only_a_run_with_children_has_a_summary():
    fleet = Fleet(33)
    jobs = fleet.seed_jobs(1, 3, T0)
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    assert views.summary(snap, SCHEMA, fleet.specs[1]["verstr"]) is None
    assert views.summary(snap, SCHEMA, "1.0.0-dev.nope") is None
    assert views.failures(snap, SCHEMA, fleet.specs[1]["verstr"]) is None
    assert views.is_job(snap, jobs[0]) and not views.is_job(snap, fleet.specs[1]["verstr"])


def test_answers_are_memoized():
    fleet = Fleet(34)
    jobs = fleet.seed_jobs(1, 30, T0, live=3)
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    assert views.summary(snap, SCHEMA, jobs[0]) is views.summary(snap, SCHEMA, jobs[0])
    assert views.failures(snap, SCHEMA, jobs[0]) is views.failures(snap, SCHEMA, jobs[0])


def _failing_job():
    """40 runs: 10 OOM (8 of them opt=big, on host gpu1 but one), 5 NaN, 25 fine."""
    fleet = Fleet(35)
    job = fleet.append(state=fleet.ended(T0, code=0))
    for i in range(40):
        oom, nan = i < 10, 10 <= i < 15
        state = fleet.ended(T0, code=1 if oom or nan else 0)
        state["error_summary"] = (f"CUDA out of memory. Tried {i}.5 GiB" if oom
                                  else f"loss is NaN at step {i}" if nan else None)
        state["host"] = "gpu1" if oom and i else f"gpu{i % 4 + 2}"
        kid = fleet.append(parent=job, state=state)
        fleet.edit(fleet.index(kid), opt="big" if i < 8 else ("adam" if i % 2 else "sgd"))
    return fleet, job


def test_failures_cluster_by_signature_with_hosts_and_overrepresented_params():
    fleet, job = _failing_job()
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    body = views.failures(snap, SCHEMA, job)
    assert body["total_failed"] == 15
    oom, nan = body["clusters"]
    assert (oom["count"], nan["count"]) == (10, 5)
    assert oom["share"] == pytest.approx(10 / 15)
    assert oom["label"].startswith("CUDA out of memory")
    assert oom["hosts"][0] == {"host": "gpu1", "count": 9}
    assert len(oom["hosts"]) <= 5
    assert oom["params"][0] == {"key": "opt", "value": "big", "share": 0.8, "base_share": 0.2}
    members = {r["verstr"]: r for r in _members(snap, job)}
    assert signature(members[oom["example_verstr"]]) == oom["sig"]
    ended = sorted(r["finished_at"] for r in members.values() if signature(r) == oom["sig"])
    assert (oom["first_at"], oom["last_at"]) == (ended[0], ended[-1])


def test_failure_counts_match_a_brute_force_walk_and_the_limit_caps_clusters():
    fleet = Fleet(36)
    jobs = fleet.seed_jobs(2, 200, T0, live=20)
    views = JobViews(LeaderboardCache())
    for _ in range(4):
        snap = fleet.snapshot()
        for job in jobs:
            counts = {}
            for row in _members(snap, job):
                if signature(row):
                    counts[signature(row)] = counts.get(signature(row), 0) + 1
            body = views.failures(snap, SCHEMA, job, limit=2)
            assert body["total_failed"] == sum(counts.values())
            want = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
            assert [(c["sig"], c["count"]) for c in body["clusters"]] == want
        fleet.mutate(T0, 10, reparent=False)


def test_a_param_too_rare_in_the_cluster_is_not_reported():
    fleet, job = _failing_job()
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    nan = views.failures(snap, SCHEMA, job)["clusters"][1]
    # adam/sgd split the NaN runs about as they split the job: no lift worth a mention.
    assert all(p["share"] > p["base_share"] for p in nan["params"])
    assert all(p["share"] * 5 >= 2 for p in nan["params"])


def test_the_detail_fleet_reads_counts_and_expected_from_the_rollup():
    fleet = Fleet(37)
    jobs = fleet.seed_jobs(1, 30, T0, live=4)
    fleet.edit(0, values={"loss": 0.1})
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    status = views.detail_status(snap, SCHEMA, jobs[0])
    rollup = views.cache.job_rollup(snap, SCHEMA, jobs[0])
    counts = rollup["counts"]
    assert status["fleet"] == {"expected": rollup["expected"], "counts": {
        "running": counts["running"], "succeeded": counts["succeeded"],
        "failed": counts["failed"], "stuck": counts["stuck"], "created": counts["waiting"],
        "waiting": max(0, rollup["expected"] - rollup["total"])}}
    assert status["kind"] == "outer" and len(status["children"]) == 30
    assert status["tree_status"] == views.summary(snap, SCHEMA, jobs[0])["tree_status"]
    assert views.detail_status(snap, SCHEMA, fleet.specs[1]["verstr"]) is None


def test_without_a_goal_the_summary_tracks_the_most_common_metrics_unranked():
    fleet = Fleet(38)
    jobs = fleet.seed_jobs(1, 40, T0)
    for i in range(1, 41):
        fleet.edit(i, values={"loss": i / 10, **({"acc": 0.5} if i % 4 else {})})
    views, snap = JobViews(LeaderboardCache()), fleet.snapshot()
    summary = views.summary(snap, {}, jobs[0])
    assert summary["ranked"] is False and summary["metric"] == "loss"
    assert set(summary["metrics"]) == {"loss", "acc"}
    loss = summary["metrics"]["loss"]
    assert (loss["n"], loss["min"], loss["max"]) == (40, 0.1, 4.0)
    assert loss["best"] is None and loss["best_verstr"] is None
    assert sum(b["count"] for b in loss["hist"]) == 40 and loss["p50"] is not None
    assert summary["top"] == []
    job = views.job_summary(snap, {}, jobs[0])
    assert job["metric"] == "loss" and job["best"] is None and job["best_verstr"] is None
    assert sum(job["spread"]) == 40


def test_the_goal_less_fallback_keeps_the_five_most_common_metrics():
    fleet = Fleet(39)
    jobs = fleet.seed_jobs(1, 20, T0)
    for i in range(1, 21):
        fleet.edit(i, values={f"m{k}": 1.0 for k in range(7) if i <= 20 - k})
    summary = JobViews(LeaderboardCache()).summary(fleet.snapshot(), {}, jobs[0])
    assert sorted(summary["metrics"]) == ["m0", "m1", "m2", "m3", "m4"]
    assert summary["metric"] == "m0"


def test_the_goal_less_fallback_follows_metrics_logged_in_a_later_generation():
    fleet = Fleet(40)
    jobs = fleet.seed_jobs(1, 10, T0)
    for i in range(11):  # the job's own row too
        fleet.edit(i, values={})
    views = JobViews(LeaderboardCache())
    assert views.summary(fleet.snapshot(), {}, jobs[0])["metric"] is None
    for i in range(1, 11):
        fleet.edit(i, values={"f1": i / 10})
    summary = views.summary(fleet.snapshot(), {}, jobs[0])
    assert summary["metric"] == "f1" and summary["metrics"]["f1"]["n"] == 10


def test_a_declared_goal_ranks_as_before():
    fleet = Fleet(41)
    jobs = fleet.seed_jobs(1, 20, T0)
    summary = JobViews(LeaderboardCache()).summary(fleet.snapshot(), SCHEMA, jobs[0])
    assert summary["ranked"] is True and summary["top"]
