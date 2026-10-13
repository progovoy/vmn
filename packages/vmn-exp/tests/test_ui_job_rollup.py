"""Plan 23 S1: a job's rollup over its whole subtree, carried across index
generations by deltas, must answer what a brute-force walk of the same
snapshot answers — through re-parenting, removal, archiving, nested jobs and
live runs going stale between time buckets."""
import datetime
import math

import pytest
from job_rollup_reference import annotated, exact_quantile, jobs, rollup
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui import job_rollup
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMAS = [{}, {"loss": {"goal": "min", "primary": True}},
           {"acc": {"goal": "max"}, "loss": {"goal": "min"}, "val_*": {"goal": "min"}}]


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _close(got, want, rel=0.011):
    return abs(got - want) <= rel * abs(want) + 1e-9


def _check_metric(got, want):
    if want is None:
        assert got is None
        return
    for key in ("n", "min", "max", "best", "best_verstr"):
        assert got[key] == want[key], key
    assert math.isclose(got["mean"], want["mean"], rel_tol=1e-9, abs_tol=1e-9)
    for key, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
        assert _close(got[key], exact_quantile(want["values"], q)), key
    assert sum(b["count"] for b in got["hist"]) == want["n"]


def _check(got, want):
    for key in ("total", "counts", "done", "expected", "throughput_per_min",
                "started_at", "finished_at"):
        assert got[key] == want[key], key
    assert got["failures"] == [{"sig": s, "label": got["failures"][i]["label"], "count": n}
                               for i, (s, n) in enumerate(want["failures"])]
    assert set(got["metrics"]) == set(want["metrics"])
    for name, metric in want["metrics"].items():
        _check_metric(got["metrics"][name], metric)
    if want["durations"]:
        assert _close(got["duration"]["p50"], exact_quantile(want["durations"], 0.5))
    else:
        assert got["duration"]["p50"] is None


def _check_all(cache, snap, schema):
    rows = annotated(snap)
    summaries = cache.job_rollups(snap, schema)
    assert set(summaries) == set(jobs(rows))
    for verstr in jobs(rows):
        want = rollup(rows, verstr, schema)
        _check(cache.job_rollup(snap, schema, verstr), want)
        assert summaries[verstr]["total"] == want["total"]
        assert summaries[verstr]["counts"] == want["counts"]


def _richer(fleet, now, count):
    """Some runs end (with times and reasons), some start again."""
    for i in fleet.rng.sample(range(len(fleet.specs)), count):
        fleet.set_state(i, fleet.ended(now) if fleet.rng.random() < 0.8 else None)


@pytest.mark.parametrize("seed", range(6))
def test_rollups_match_a_brute_force_walk_across_generations(monkeypatch, seed):
    fleet = Fleet(seed)
    fleet.seed(300, T0, sweeps=5, live=12)
    _richer(fleet, T0, 120)
    cache = LeaderboardCache()
    now = T0
    for generation in range(14):
        _at(monkeypatch, now)
        snap = fleet.snapshot()
        for schema in SCHEMAS:
            _check_all(cache, snap, schema)
        now += datetime.timedelta(seconds=fleet.rng.choice([0, 1, 3, 45, 70]))
        fleet.mutate(now, fleet.rng.choice([1, 4, 12]))
        _richer(fleet, now, fleet.rng.choice([0, 3, 8]))


def test_live_runs_move_the_rollup_between_time_buckets(monkeypatch):
    fleet = Fleet(11)
    fleet.seed_jobs(3, 40, T0, live=20)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    for later in (0, 20, 61, 200):
        _at(monkeypatch, T0 + datetime.timedelta(seconds=later))
        _check_all(cache, snap, SCHEMAS[1])


def test_nested_jobs_each_roll_up_their_own_subtree(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(12)
    top = fleet.append(state=fleet.ended(T0))
    mid = fleet.append(parent=top, state=fleet.ended(T0))
    for _ in range(5):
        fleet.append(parent=mid, state=fleet.ended(T0, code=1))
        fleet.append(parent=top, state=fleet.ended(T0, code=0))
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert cache.job_rollup(snap, {}, top)["total"] == 11
    assert cache.job_rollup(snap, {}, mid)["total"] == 5
    assert cache.job_rollup(snap, {}, mid)["counts"]["failed"] == 5
    _check_all(cache, snap, SCHEMAS[1])
    # The middle job moves out from under the top one, its subtree with it.
    fleet.edit(fleet.index(mid), parent=None)
    snap = fleet.snapshot()
    assert cache.job_rollup(snap, {}, top)["total"] == 5
    _check_all(cache, snap, SCHEMAS[1])


def test_removing_a_jobs_best_run_recomputes_its_extremes(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(13)
    fleet.seed_jobs(1, 30, T0)
    schema = SCHEMAS[1]
    cache, snap = LeaderboardCache(), fleet.snapshot()
    job = fleet.specs[0]["verstr"]
    best = cache.job_rollup(snap, schema, job)["metrics"]["loss"]["best_verstr"]
    fleet.edit(fleet.index(best), values={"loss": 99.0})
    snap = fleet.snapshot()
    assert cache.job_rollup(snap, schema, job)["metrics"]["loss"]["best_verstr"] != best
    _check_all(cache, snap, schema)
    fleet.remove(fleet.index(cache.job_rollup(snap, schema, job)["metrics"]["loss"]["best_verstr"]))
    _check_all(cache, fleet.snapshot(), schema)


def test_archived_runs_are_left_out(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(14)
    fleet.seed_jobs(1, 10, T0)
    cache = LeaderboardCache()
    job = fleet.specs[0]["verstr"]
    fleet.edit(3, archived=True)
    assert cache.job_rollup(fleet.snapshot(), {}, job)["total"] == 9


def test_only_runs_with_children_are_jobs(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(15)
    fleet.seed_jobs(1, 3, T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert cache.job_rollup(snap, {}, fleet.specs[1]["verstr"]) is None
    assert cache.job_rollup(snap, {}, "1.0.0-dev.nope") is None


def test_a_generation_moves_the_rollups_on_instead_of_rebuilding(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(16)
    fleet.seed_jobs(4, 100, T0, live=10)
    cache = LeaderboardCache()
    cache.job_rollups(fleet.snapshot(), SCHEMAS[1])
    builds = []
    real = job_rollup.StaticRollups.build
    monkeypatch.setattr(job_rollup.StaticRollups, "build",
                        classmethod(lambda cls, *a: builds.append(1) or real(*a)))
    for _ in range(3):
        fleet.mutate(T0, 5, removals=False, reparent=False)
        snap = fleet.snapshot()
        cache.job_rollups(snap, SCHEMAS[1])
        _check_all(cache, snap, SCHEMAS[1])
    assert builds == []


def test_answers_are_memoized_per_generation_and_bucket(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(17)
    fleet.seed_jobs(2, 20, T0, live=3)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    job = fleet.specs[0]["verstr"]
    assert cache.job_rollup(snap, {}, job) is cache.job_rollup(snap, {}, job)
    assert cache.job_rollups(snap, {}) is cache.job_rollups(snap, {})
