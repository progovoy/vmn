"""Plan 32 follow-up: the board's goal for a metric is the conf's, else the
one goal its runs declare. Runs declaring different goals give no goal (no
best, ranking or verdict) and the schema says ``goal_conflict`` — never the
latest run's goal, silently. Compare (F9) resolves through the same function."""
from collections import Counter

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import sort_by_metric
from vmn_exp.core.metric_schema import (
    declared_schema,
    effective_schema,
    metric_goal,
    resolve_goal,
    with_goal_counts,
    with_resolved_goals,
)

CONFLICT = {"goal_conflict": True}


def test_runs_declaring_different_goals_leave_the_metric_without_one():
    declared = declared_schema([
        {"loss": {"goal": "min", "hidden": True}}, {"loss": {"goal": "max"}},
        {"loss": {"goal": "max"}}])
    assert declared == {"loss": {"hidden": True, **CONFLICT}}
    assert metric_goal(declared, "loss") is None


def test_runs_agreeing_on_a_goal_give_it_and_other_fields_still_take_the_latest():
    declared = declared_schema([
        {"loss": {"goal": "min", "chart": "bars"}}, {"loss": {"chart": "table"}},
        {"loss": {"goal": "min"}}])
    assert declared == {"loss": {"goal": "min", "chart": "table"}}


def test_the_conf_goal_wins_over_conflicting_runs_exact_or_glob():
    declared = {"loss": {"hidden": True, **CONFLICT}, "acc": {"goal": "min"}}
    assert effective_schema({"loss": {"goal": "min"}}, declared)["loss"] == {"goal": "min"}
    schema = effective_schema({"lo*": {"goal": "max"}, "a*": {"goal": "max"}}, declared)
    assert schema["loss"] == {"hidden": True, "goal": "max"}
    assert metric_goal(schema, "loss") == "max"
    assert metric_goal(schema, "acc") == "max"


def test_a_conflict_is_not_resolved_by_a_run_declared_glob():
    schema = effective_schema({}, {"val_*": {"goal": "max"}, "val_loss": dict(CONFLICT)})
    assert metric_goal(schema, "val_loss") is None
    assert "goal" not in with_resolved_goals(schema, ["val_loss"])["val_loss"]


def test_a_conflicted_metric_sorts_low_first_like_one_without_a_goal():
    rows = [{"idx": i, "verstr": f"v{i}", "metrics": {"loss": v}} for i, v in enumerate((0.5, 0.1, 0.9))]
    ranked = sort_by_metric(rows, {"loss": dict(CONFLICT)}, sort="loss")
    assert [r["metrics"]["loss"] for r in ranked] == [0.1, 0.5, 0.9]


def test_the_payload_counts_the_runs_behind_each_goal():
    schema = {"loss": dict(CONFLICT), "acc": {"goal": "max"}}
    counts = {"loss": {"min": 2, "max": 1}, "acc": {"max": 3}}
    assert with_goal_counts(schema, counts) == {
        "loss": {**CONFLICT, "goals": {"min": 2, "max": 1}}, "acc": {"goal": "max"}}


def test_one_function_resolves_a_goal_for_board_and_compare():
    assert resolve_goal("max", ["min", "min"]) == {"goal": "max"}
    assert resolve_goal(None, ["min", None, "min"]) == {"goal": "min"}
    assert resolve_goal(None, [None]) == {"goal": None}
    assert resolve_goal(None, ["min", "max"]) == {"goal": None, "goal_conflict": True}


def test_a_snapshot_counts_its_runs_goals():
    rows = [{"verstr": v, "timestamp": f"2026-01-0{i}"} for i, v in enumerate("abc", 1)]
    snap = IndexSnapshot.build("app", 1, rows, {}, declared_defs={
        "a": {"loss": {"goal": "min"}}, "b": {"loss": {"goal": "max"}}, "c": {"loss": {"goal": "max"}}})
    assert snap.declared_schema() == {"loss": dict(CONFLICT)}
    assert snap.goal_counts() == {"loss": Counter(min=1, max=2)}
