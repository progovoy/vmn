"""The effective metrics schema: conf.yml plus goals/hidden runs declare.

A run's ``define_metric(goal=..., hidden=...)`` fills in names the conf does
not declare (the latest run wins) — for sort direction and hidden columns
only, never another run's summary.
"""
from exp_helpers import _bootstrap, _storage

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import sort_by_metric
from vmn_exp.core.metric_schema import (
    declared_fields,
    declared_schema,
    effective_schema,
    hidden_metrics,
    metric_goal,
)
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import list_runs


def _rows(values):
    return [{"idx": i, "verstr": f"v{i}", "metrics": {"val_acc": v}}
            for i, v in enumerate(values, 1)]


def test_conf_goal_beats_declared_goal():
    conf = {"loss": {"goal": "min"}}
    declared = {"loss": {"goal": "max"}, "acc": {"goal": "max", "hidden": True}}
    assert effective_schema(conf, declared) == {
        "loss": {"goal": "min"}, "acc": {"goal": "max", "hidden": True}}


def test_declared_fields_keep_only_goal_and_hidden():
    defs = {"loss": {"goal": "min", "summary": "mean", "step_metric": "epoch"},
            "lr": {"hidden": True}, "x": {"step_metric": "epoch"}}
    assert declared_fields(defs) == {"loss": {"goal": "min"}, "lr": {"hidden": True}}


def test_latest_run_declaration_wins():
    assert declared_schema([{"loss": {"goal": "min"}}, {"loss": {"goal": "max"}}]) == {
        "loss": {"goal": "max"}}
    rows = [{"verstr": "new", "timestamp": "2026-01-02"},
            {"verstr": "old", "timestamp": "2026-01-01"}]
    snap = IndexSnapshot.build(
        "app", 1, rows, {},
        declared_defs={"new": {"loss": {"goal": "max"}}, "old": {"loss": {"goal": "min"}}},
    )
    assert snap.declared_schema() == {"loss": {"goal": "max"}}
    assert snap.summarized({"loss": {"goal": "min"}}).declared_schema() == {
        "loss": {"goal": "max"}}


def test_glob_goal_sets_sort_direction():
    schema = {"val_*": {"goal": "max"}}
    assert metric_goal(schema, "val_acc") == "max"
    ranked = sort_by_metric(_rows([0.1, 0.9, 0.5]), schema, sort="val_acc")
    assert [r["metrics"]["val_acc"] for r in ranked] == [0.9, 0.5, 0.1]


def test_exact_goal_beats_a_glob_goal():
    schema = {"val_*": {"goal": "max"}, "val_loss": {"goal": "min"}}
    assert metric_goal(schema, "val_loss") == "min"
    assert metric_goal(schema, "other") is None


def test_hidden_metrics_from_run_then_schema():
    run_defs = {"grad_*": {"hidden": True}, "lr": {"hidden": False}}
    schema = {"lr": {"hidden": True}, "mem": {"hidden": True}}
    names = ["grad_norm", "lr", "mem", "loss"]
    assert hidden_metrics(names, run_defs, schema) == ["grad_norm", "mem"]


def _run(app_layout, accs, goal=None):
    with start_run(app_layout.app_name) as run:
        if goal:
            run.define_metric("acc", goal=goal)
        for step, acc in enumerate(accs):
            run.log_metric("acc", acc, step=step)
        return run.id


def test_declared_goal_sorts_without_conf(app_layout):
    _bootstrap(app_layout)
    low = _run(app_layout, [0.1, 0.2])
    high = _run(app_layout, [0.8, 0.9], goal="max")
    for use_index in (True, False):
        rows = list_runs(app_layout.app_name, sort="acc", use_index=use_index)
        assert [r["verstr"] for r in rows] == [high, low]


def test_declared_goal_does_not_change_another_runs_summary(app_layout):
    _bootstrap(app_layout)
    other = _run(app_layout, [0.9, 0.1])
    _run(app_layout, [0.5, 0.6], goal="max")
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))
    assert next(r for r in rows if r["verstr"] == other)["metrics"]["acc"] == 0.1
