"""Plan 31 §2 / plan 32: baselines share the Outer runs row's value function.
A paired child's value comes from the board's ``job_agg_value`` alone (own
or subtree best, never one for one side and the other for the other); a pair
missing it is unpaired and counted; the rollup deltas carry ``rolled`` and,
without pairs, the chip compares it. The outer run's summary carries
``rolled`` for its KPI tile."""
from leaderboard_group_rows import run, snapshot, v
from test_ui_baseline_views import RULE, SCHEMA, _specs
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.baseline_views import BaselineViews
from vmn_exp.ui.job_views import JobViews

MATCH = {"match": ["params.table_name", "params.model_type"]}


def _views(ui):
    cache = lb.LeaderboardCache(conf_of=lambda snap: ({}, ui))
    return BaselineViews(JobViews(cache))


def _nested():
    """Date 2025-12 of both launches (runs 13, 33) logs no best_value of its
    own; a run under each does (0.5, 2.0). Date 2024-06 of the target (30)
    has a child better than its own value."""
    specs = _specs() + [run(50, parent=13, metrics={"best_value": 0.5}),
                        run(51, parent=33, metrics={"best_value": 2.0}),
                        run(52, parent=30, metrics={"best_value": 5.0})]
    return [dict(s, metrics={}) if s["n"] in (13, 33) else s for s in specs]


def test_own_pairs_only_dates_logging_their_own_value():
    ui = dict(RULE, job_aggregate={"value": "own"})
    body = _views(ui).baseline(snapshot(_nested()), SCHEMA, v(3))
    assert [p["label"] for p in body["pairs"]] == ["2024-06", "2024-12", "2025-06"]
    assert body["pairs"][0]["value"] == 1.1  # its own, not its child's 5.0
    assert body["pairs_total"] == 4
    assert (body["chip"]["paired"], body["chip"]["total"]) == (3, 4)


def test_best_takes_every_dates_subtree_best_on_both_sides():
    body = _views(RULE).baseline(snapshot(_nested()), SCHEMA, v(3))
    assert [p["value"] for p in body["pairs"]] == [5.0, 0.2, 0.1, 2.0]
    assert [p["baseline"] for p in body["pairs"]] == [1.0, 1.0, 1.0, 0.5]
    assert (body["chip"]["paired"], body["chip"]["total"]) == (4, 4)


def test_the_rollup_deltas_carry_rolled():
    ui = dict(RULE, job_aggregate={"agg": "median"})
    rolled = _views(ui).baseline(snapshot(_specs()), SCHEMA, v(3))["rolled"]
    assert (rolled["agg"], rolled["by"], rolled["source"]) == ("median", "children", "best")
    assert rolled["value"] == 0.65 and rolled["baseline"] == 1.0
    assert rolled["delta"] == -0.35 and rolled["better"] is False


def test_without_pairs_the_chip_compares_rolled():
    ui = {"baseline": MATCH, "job_aggregate": {"agg": "median"}}
    chip = _views(ui).baseline(snapshot(_specs()), SCHEMA, v(3))["chip"]
    assert chip["state"] == "worse"
    assert chip["text"] == "▼ median best_value 0.65 (baseline 1)"
    best = _views({"baseline": MATCH}).baseline(snapshot(_specs()), SCHEMA, v(3))["chip"]
    assert best["text"] == "▲ best_value 1.2 (baseline 1)"


def test_the_outer_runs_summary_carries_rolled():
    cache = lb.LeaderboardCache(conf_of=lambda snap: ({}, {"job_aggregate": {"agg": "median"}}))
    summary = JobViews(cache).summary(snapshot(_specs()), SCHEMA, v(3))
    assert summary["rolled"]["agg"] == "median" and summary["rolled"]["value"] == 0.65
