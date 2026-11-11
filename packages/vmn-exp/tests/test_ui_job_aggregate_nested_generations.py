"""Plan 35 §2 across index generations: with ``nested`` every carrier below
a job is a unit, without it the ones under another carrier are counted in
``nested_skipped``; both answer what a fresh brute-force walk of the same
snapshot answers after random deltas (re-dated runs, re-links, removals)."""
import datetime

import pytest
from job_rollup_reference import annotated
from job_rollup_reference import rolled as reference
from leaderboard_fleet import T0
from test_ui_job_aggregate_generations import SCHEMA, DateFleet, _at, _top
from vmn_exp.ui.job_aggregate import JobAgg
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

AGGS = [JobAgg("median", by, "best", None, nested)
        for by in ("field:params.trade_date", "kind:date") for nested in (False, True)]


def _nest(fleet, count):
    """Under *count* runs right below a root, made dates, a date of its own
    (``n0``..``n2``: some nested dates share a value)."""
    roots = {s["verstr"] for s in fleet.specs if s["parent"] is None}
    mids = [i for i, s in enumerate(fleet.specs) if s["parent"] in roots]
    for n, i in enumerate(fleet.rng.sample(mids, count)):
        fleet.edit(i, date="d1", kind="date")
        fleet.append(parent=fleet.specs[i]["verstr"], state=fleet.ended(T0))
        fleet.edit(len(fleet.specs) - 1, date=f"n{n % 3}", kind="date")


def _check(cache, snap):
    """Every top-level job's ``rolled`` against the walk; how many nested
    carriers were skipped in all."""
    rows, skipped = annotated(snap), 0
    for agg in AGGS:
        got = cache.job_aggregates.rolled(snap, SCHEMA, agg)
        for job in _top(rows):
            want = reference(rows, job, agg.by, agg.value, "loss", agg.agg, False, agg.nested)
            mine = got[job]
            assert (mine["n"], mine["of"], mine["conflicts"], mine["nested_skipped"]) == (
                want["n"], want["of"], want["conflicts"], want["nested_skipped"]), (agg, job)
            assert (mine["value"] is None) == (want["value"] is None), (agg, job)
            if want["value"] is not None:
                assert mine["value"] == pytest.approx(want["value"]), (agg, job)
            skipped += mine["nested_skipped"]
    return skipped


@pytest.mark.parametrize("seed", range(4))
def test_nested_units_match_a_brute_force_walk_across_generations(monkeypatch, seed):
    fleet = DateFleet(seed)
    fleet.seed(240, T0, sweeps=5, live=10)
    for root in fleet.rng.sample([s["verstr"] for s in fleet.specs], 12):
        fleet.append(parent=root, state=fleet.ended(T0))
    _nest(fleet, 8)
    cache, now = LeaderboardCache(), T0
    _at(monkeypatch, now)
    assert _check(cache, fleet.snapshot()) > 0
    for _ in range(10):
        now += datetime.timedelta(seconds=fleet.rng.choice([0, 1, 45, 70]))
        fleet.mutate(now, fleet.rng.choice([1, 4, 12]))
        fleet.redate(fleet.rng.choice([0, 1, 3]))
        _at(monkeypatch, now)
        _check(cache, fleet.snapshot())
