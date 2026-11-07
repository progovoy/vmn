"""Plan 31 §2: ``rolled`` carried across index generations by the cache's
deltas (a trial improving a date's best, the holder of a best removed, a
re-link, archiving, live runs) answers what a fresh brute-force walk of the
same snapshot answers."""
import datetime

import pytest
from job_rollup_reference import annotated, jobs
from job_rollup_reference import rolled as reference
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.job_aggregate import JobAgg
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod
from vmn_exp.ui import job_rollup

SCHEMA = {"loss": {"goal": "min", "primary": True}, "acc": {"goal": "max"}}
DATES = ["d1", "d2", "d3", "d4", None, None]
KINDS = ["date", None, None]
AGGS = [JobAgg(agg, by, value, metric)
        for by in ("children", "field:params.trade_date", "kind:date", "runs")
        for agg, value, metric in (("median", "best", None), ("best10", "own", "acc"),
                                   ("mean", "own", None), ("min", "best", "acc"),
                                   ("best", "best", None))]


class DateFleet(Fleet):
    """A fleet whose runs carry a ``trade_date`` param and a ``kind`` tag now and then."""

    def _fold(self, i):
        spec = self.specs[i]
        if "date" not in spec:
            spec["date"], spec["kind"] = self.rng.choice(DATES), self.rng.choice(KINDS)
        row = super()._fold(i)
        params = dict(row["params"], **({"trade_date": spec["date"]} if spec["date"] else {}))
        return dict(row, params=params, tags={"kind": spec["kind"]} if spec["kind"] else {})

    def redate(self, count):
        for i in self.rng.sample(range(len(self.specs)), count):
            self.edit(i, date=self.rng.choice(DATES), kind=self.rng.choice(KINDS))


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _top(rows):
    found = set(jobs(rows))
    parent = {row["verstr"]: row.get("parent") for row in rows}
    return {j for j in found if parent.get(j) not in found or parent.get(j) == j}


def _check(cache, snap):
    rows = annotated(snap)
    top = _top(rows)
    for agg in AGGS:
        got = cache.job_aggregates.rolled(snap, SCHEMA, agg)
        assert set(got) == top
        metric = agg.metric or "loss"
        for job in top:
            want = reference(rows, job, agg.by, agg.value, metric, agg.agg, metric == "acc")
            mine = got[job]
            assert (mine["n"], mine["of"], mine["conflicts"]) == (
                want["n"], want["of"], want["conflicts"]), (agg, job)
            if want["value"] is None or mine["approx"]:
                assert (mine["value"] is None) == (want["value"] is None), (agg, job)
                if want["value"] is not None:
                    assert abs(mine["value"] - want["value"]) <= 0.011 * abs(want["value"]) + 1e-9
            else:
                assert mine["value"] == pytest.approx(want["value"]), (agg, job)


@pytest.mark.parametrize("seed", range(5))
def test_rolled_matches_a_brute_force_walk_across_generations(monkeypatch, seed):
    fleet = DateFleet(seed)
    fleet.seed(240, T0, sweeps=5, live=10)
    for root in fleet.rng.sample([s["verstr"] for s in fleet.specs], 12):
        fleet.append(parent=root, state=fleet.ended(T0))
    cache, now = LeaderboardCache(), T0
    for _ in range(12):
        _at(monkeypatch, now)
        _check(cache, fleet.snapshot())
        now += datetime.timedelta(seconds=fleet.rng.choice([0, 1, 45, 70]))
        fleet.mutate(now, fleet.rng.choice([1, 4, 12]))
        fleet.redate(fleet.rng.choice([0, 1, 3]))


def test_removing_a_dates_best_holder_rebuilds_it(monkeypatch):
    _at(monkeypatch, T0)
    fleet = DateFleet(3)
    fleet.seed_jobs(2, 30, T0)
    cache = LeaderboardCache()
    _check(cache, fleet.snapshot())
    for _ in range(4):
        snap = fleet.snapshot()
        job = fleet.specs[0]["verstr"]
        best = cache.job_aggregates.rolled(snap, SCHEMA, AGGS[-1])[job]["verstr"]
        if best is None:
            break
        fleet.remove(fleet.index(best))
        _check(cache, fleet.snapshot())


def test_a_generation_moves_the_units_on_instead_of_rebuilding(monkeypatch):
    _at(monkeypatch, T0)
    fleet = DateFleet(4)
    fleet.seed_jobs(4, 60, T0, live=6)
    cache = LeaderboardCache()
    _check(cache, fleet.snapshot())
    builds = []
    real = job_rollup.StaticRollups.build
    monkeypatch.setattr(job_rollup.StaticRollups, "build",
                        classmethod(lambda cls, *a: builds.append(1) or real(*a)))
    for _ in range(3):
        fleet.mutate(T0, 5, removals=False, reparent=False)
        fleet.redate(2)
        _check(cache, fleet.snapshot())
    assert builds == []
