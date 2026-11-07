"""Plan 31 §2: a chosen aggregate on the Outer runs row. Each top-level job
gets ``rolled``: its units (direct children, the nearest runs carrying a
field or a ``tags.kind``, or every run) each give one value (their subtree's
best, or their own metric with no fallback), aggregated by ``job_agg``;
checked against a brute-force walk (``job_rollup_reference.rolled``)."""
import statistics

import pytest
from job_rollup_reference import annotated
from job_rollup_reference import rolled as reference
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.ui.job_aggregate import JobAgg, job_agg_of
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"best_value": {"goal": "max", "primary": True}, "date.best_value": {"goal": "max"}}
LOWER = {"best_value": {"goal": "min", "primary": True}, "date.best_value": {"goal": "min"}}
DATES = [f"2024-{m:02d}-01" for m in range(1, 13)] + [f"2025-{m:02d}-01" for m in range(1, 5)]


def _training(n=1, dates=DATES, trials=4, own=True, start=100):
    """Training *n* → a date run per date (``date.best_value`` its own unless
    not *own*) → *trials* trials logging ``best_value``."""
    specs, at = [run(n, tags={"kind": "launch"})], start
    for i, date in enumerate(dates):
        date_n, at = at, at + 1
        values = [((i * 7 + t * 3) % 11) / 10 for t in range(trials)]
        specs.append(run(date_n, parent=n, params={"trade_date": date}, tags={"kind": "date"},
                         metrics={"date.best_value": max(values)} if own else {}))
        for t, value in enumerate(values):
            specs.append(run(at, parent=date_n, metrics={"best_value": value}))
            at += 1
    return specs


def _rolled(specs, agg, schema=SCHEMA, job=1):
    snap = snapshot(specs)
    return LeaderboardCache().job_aggregates.rolled(snap, schema, agg)[v(job)], annotated(snap)


def _want(rows, agg, schema=SCHEMA, job=1):
    metric = agg.metric or "best_value"
    goal = schema.get(metric, {}).get("goal")
    return reference(rows, v(job), agg.by, agg.value, metric, agg.agg,
                     None if goal is None else goal == "max")


@pytest.mark.parametrize("name", ["median", "best10", "min", "mean", "max", "worst10", "best"])
def test_the_aggregate_of_the_date_bests_is_exact(name):
    agg = JobAgg(agg=name)
    got, rows = _rolled(_training(), agg)
    want = _want(rows, agg)
    assert got["value"] == pytest.approx(want["value"])
    assert (got["n"], got["of"], got["conflicts"]) == (16, 16, 0)
    assert got["approx"] is False
    assert (got["agg"], got["by"], got["source"], got["metric"]) == (
        name, "children", "best", "best_value")


def test_a_value_names_the_unit_holding_it():
    specs = _training()
    dates = {s["n"]: max(x["metrics"]["best_value"] for x in specs if x["meta"].get("parent")
                         == v(s["n"])) for s in specs if s["params"].get("trade_date")}
    ordered = sorted((best, v(n)) for n, best in dates.items())
    got, _ = _rolled(specs, JobAgg(agg="median"))
    assert got["value"] == pytest.approx(statistics.median(dates.values()))
    assert got["verstr"] == ordered[7][1]  # the lower neighbour of 16
    assert _rolled(specs, JobAgg(agg="min"))[0]["verstr"] == ordered[0][1]
    assert _rolled(specs, JobAgg(agg="mean"))[0]["verstr"] is None


def test_own_never_falls_back_to_the_subtree_best():
    specs = _training()
    for spec in specs:
        if spec["params"].get("trade_date") in DATES[:4]:
            spec["metrics"] = {}
    agg = JobAgg(agg="median", value="own", metric="date.best_value")
    got, rows = _rolled(specs, agg)
    assert (got["n"], got["of"]) == (12, 16)
    assert got["value"] == pytest.approx(_want(rows, agg)["value"])
    assert got["source"] == "own"


@pytest.mark.parametrize("schema,best,worst", [(SCHEMA, "p90", "p10"), (LOWER, "p10", "p90")])
def test_the_tails_follow_the_goal_and_name_their_percentile(schema, best, worst):
    for name, label in (("best10", best), ("worst10", worst)):
        agg = JobAgg(agg=name)
        got, rows = _rolled(_training(), agg, schema)
        assert got["percentile"] == label
        assert got["value"] == pytest.approx(_want(rows, agg, schema)["value"])
    assert _rolled(_training(), JobAgg(agg="median"))[0]["percentile"] is None


def test_without_a_goal_there_is_no_value():
    schema = {"best_value": {"primary": True}}
    got, _ = _rolled(_training(), JobAgg(agg="median"), schema)
    assert got["value"] is None and got["goal"] is None and got["of"] == 16


def test_running_children_count():
    specs = _training()
    date = next(s for s in specs if s["params"].get("trade_date") == DATES[0])
    date["state"] = "running"
    late = run(999, state="running", parent=1, params={"trade_date": "2026-01-01"})
    got, _ = _rolled(specs + [late], JobAgg(agg="median"))
    assert (got["n"], got["of"]) == (16, 17)  # the new date has no value yet


def test_archived_children_are_left_out():
    specs = _training()
    date = next(s for s in specs if s["params"].get("trade_date") == DATES[0])
    date["meta"]["archived"] = True
    agg = JobAgg(agg="mean")
    got, rows = _rolled(specs, agg)
    assert got["of"] == 15
    assert got["value"] == pytest.approx(_want(rows, agg)["value"])


def _fgm(dup=False):
    """fgm's shape: training → date (varying names) → prep + study → pair
    studies → trials, refit runs under some trials, some trials right under
    the study; *dup* reruns one date."""
    specs, at = [run(1, tags={"kind": "launch"})], 100
    dates = DATES + ([DATES[3]] if dup else [])
    for i, date in enumerate(dates):
        d, prep, study = at, at + 1, at + 2
        at += 3
        specs += [run(d, parent=1, params={"trade_date": date}, tags={"kind": "date"},
                      name=f"wf-{i}-{date}", metrics={"date.best_value": 0.1 * (i % 7)}),
                  run(prep, parent=d), run(study, parent=d, tags={"kind": "study"})]
        for p in range(2):
            pair = at
            specs.append(run(pair, parent=study, metrics={"best_value": 0.05 * (i + p)}))
            at += 1
            for t in range(3):
                specs.append(run(at, parent=pair, metrics={"value": t}))
                if t == 0:
                    specs.append(run(at + 1, parent=at, metrics={"value": 9}))  # a refit
                    at += 1
                at += 1
        specs.append(run(at, parent=study, metrics={"best_value": 0.0}))  # a gbm trial
        at += 1
    return specs


@pytest.mark.parametrize("by", ["field:params.trade_date", "kind:date"])
def test_dates_are_the_units_in_fgms_shape(by):
    agg = JobAgg(agg="median", by=by, value="own", metric="date.best_value")
    got, rows = _rolled(_fgm(), agg)
    assert (got["n"], got["of"], got["conflicts"]) == (16, 16, 0)
    assert got["value"] == pytest.approx(_want(rows, agg)["value"])


def test_a_rerun_date_is_a_counted_conflict_left_out():
    agg = JobAgg(agg="median", by="field:params.trade_date", value="own",
                 metric="date.best_value")
    got, rows = _rolled(_fgm(dup=True), agg)
    assert (got["n"], got["of"], got["conflicts"]) == (15, 16, 1)
    assert got["value"] == pytest.approx(_want(rows, agg)["value"])


def test_the_aggregate_metric_may_differ_from_the_main_one():
    agg = JobAgg(agg="max", by="field:params.trade_date", value="best", metric="best_value")
    got, rows = _rolled(_fgm(), agg)
    assert got["value"] == pytest.approx(_want(rows, agg)["value"])
    own = JobAgg(agg="max", by="field:params.trade_date", value="own", metric="date.best_value")
    assert _rolled(_fgm(), own)[0]["value"] == pytest.approx(0.6)
    assert _rolled(_fgm(), own)[0]["metric"] == "date.best_value"


def test_kind_finds_its_units_at_depth_two():
    specs = [run(1)]
    for g in range(3):
        specs.append(run(10 + g, parent=1))
        for d in range(2):
            n = 100 + g * 10 + d
            specs.append(run(n, parent=10 + g, tags={"kind": "date"}))
            specs.append(run(n + 500, parent=n, metrics={"best_value": g + d / 10}))
    agg = JobAgg(agg="mean", by="kind:date")
    got, rows = _rolled(specs, agg)
    assert (got["n"], got["of"]) == (6, 6)
    assert got["value"] == pytest.approx(_want(rows, agg)["value"])


def test_the_runs_sketch_is_within_one_percent():
    agg = JobAgg(agg="median", by="runs")
    got, rows = _rolled(_training(trials=40), agg)
    want = _want(rows, agg)
    assert got["approx"] is True
    assert abs(got["value"] - want["value"]) <= 0.011 * abs(want["value"])
    assert (got["n"], got["of"]) == (want["n"], want["of"])


@pytest.mark.parametrize("by", ["children", "field:params.trade_date", "kind:date", "runs"])
def test_best_is_the_same_for_every_by(by):
    snap = snapshot(_training())
    cache = LeaderboardCache()
    got = cache.job_aggregates.rolled(snap, SCHEMA, JobAgg(by=by))[v(1)]
    assert got["value"] == cache.job_rollups(snap, SCHEMA)[v(1)]["best"]


def test_a_training_logging_its_median_matches_ours():
    """The acceptance test: fgm's training rows log ``wf.best_value_median``
    of their dates' ``date.best_value``; our rolled median equals it."""
    specs = _fgm()
    own = [s["metrics"]["date.best_value"] for s in specs if "date.best_value" in s["metrics"]]
    specs[0]["metrics"] = {"wf.best_value_median": statistics.median(own),
                           "wf.best_value_max": max(own)}
    snap = snapshot(specs)
    cache = LeaderboardCache()
    for name, logged in (("median", "wf.best_value_median"), ("max", "wf.best_value_max")):
        agg = JobAgg(agg=name, by="field:params.trade_date", value="own",
                     metric="date.best_value")
        assert cache.job_aggregates.rolled(snap, SCHEMA, agg)[v(1)]["value"] == pytest.approx(
            snapshot(specs).rows[0]["metrics"][logged])


def test_only_top_level_jobs_are_rolled():
    snap = snapshot(_training(n=1) + _training(n=2, start=500) + [run(900)])
    rolled = LeaderboardCache().job_aggregates.rolled(snap, SCHEMA, JobAgg(agg="median"))
    assert set(rolled) == {v(1), v(2)}


def test_a_jobs_page_carries_rolled_and_a_tree_page_does_not():
    snap, cache = snapshot(_training()), LeaderboardCache()
    agg = JobAgg(agg="median")
    page = cache.page(snap, SCHEMA, limit=10, top=True, job_agg=agg)
    assert page["rows"][0]["job"]["rolled"] == cache.job_aggregates.rolled(snap, SCHEMA, agg)[v(1)]
    tree = cache.page(snap, SCHEMA, limit=50, children_of=v(1))
    assert all("rolled" not in (row.get("job") or {}) for row in tree["rows"])


def test_the_answer_is_memoized_per_generation():
    snap, cache = snapshot(_training()), LeaderboardCache()
    agg = JobAgg(agg="median")
    assert cache.job_aggregates.rolled(snap, SCHEMA, agg) is cache.job_aggregates.rolled(
        snap, SCHEMA, agg)


def test_settings_give_the_default_and_the_url_overrides_them():
    ui = {"job_aggregate": {"agg": "median", "by": "field:params.trade_date", "value": "own",
                            "metric": "date.best_value"}}
    assert job_agg_of(ui) == JobAgg("median", "field:params.trade_date", "own",
                                    "date.best_value")
    assert job_agg_of(ui, agg="best10", by="children") == JobAgg(
        "best10", "children", "own", "date.best_value")
    assert job_agg_of({}) == JobAgg("best", "children", "best", None)
    assert job_agg_of({"job_aggregate": {"agg": "sum"}}) == JobAgg()  # an invalid conf: none


@pytest.mark.parametrize("bad", [dict(agg="sum"), dict(by="depth:2"), dict(by="field:metrics.x"),
                                 dict(by="kind:"), dict(value="last"), dict(metric="")])
def test_a_bad_url_value_is_refused(bad):
    with pytest.raises(ValueError):
        job_agg_of({}, **bad)
