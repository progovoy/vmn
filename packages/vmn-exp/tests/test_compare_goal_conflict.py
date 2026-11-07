"""Plan 32 F9: compare takes one goal for both runs — the app's metrics
schema, else the two runs' own declarations, else what other runs declare.
Two runs that declare different goals for a metric get no direction: the
delta says ``goal_conflict`` and names both goals."""
from test_ui_diff_from_snapshot import _snap
from test_ui_diff_summary import _log_define_metric, _log_metrics, _save_exp

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.readers import diffs as diff_reader

V1, V2, V3 = "1.0.0-dev.aaa.bbb", "1.0.0-dev.ccc.ddd", "1.0.0-dev.eee.fff"
# from_policy/to_policy: plan 32 F1 (each side's summary; None for last).
CONFLICT = {"from": 0.5, "to": 0.3, "goal": None, "param": False,
            "from_policy": None, "to_policy": None,
            "goal_conflict": True, "goals": ["min", "max"]}


def _run(storage, verstr, loss, goal=None, day=1):
    _save_exp(storage, "myapp", verstr, ts=f"2025-01-0{day}T00:00:00Z")
    if goal:
        _log_define_metric(storage, "myapp", verstr, "loss", goal)
    _log_metrics(storage, "myapp", verstr, {"loss": loss})


def _storage(tmp_path, goal1, goal2):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    _run(storage, V1, 0.5, goal1)
    _run(storage, V2, 0.3, goal2, day=2)
    return storage


def _storage_delta(storage, schema=None):
    result, err = diff_reader.experiment_diff_from_storage(storage, "myapp", V1, V2, schema=schema)
    assert err is None
    return result["metrics_delta"]


def _snapshot_delta(storage, schema=None):
    return diff_reader.experiment_diff_from_snapshot(_snap(storage), V1, V2, schema)["metrics_delta"]


def test_runs_declaring_different_goals_give_the_delta_no_direction(tmp_path):
    assert _storage_delta(_storage(tmp_path, "min", "max"))["loss"] == CONFLICT


def test_the_snapshot_compare_says_the_goals_differ_too(tmp_path):
    assert _snapshot_delta(_storage(tmp_path, "min", "max"))["loss"] == CONFLICT


def test_the_apps_schema_goal_is_the_one_goal_of_both_runs(tmp_path):
    storage = _storage(tmp_path, "min", "max")
    schema = {"loss": {"goal": "max"}}

    for delta in (_storage_delta(storage, schema), _snapshot_delta(storage, schema)):
        assert delta["loss"] == {"from": 0.5, "to": 0.3, "goal": "max", "param": False,
                                 "from_policy": "max", "to_policy": "max"}


def test_the_compared_runs_declaration_beats_a_later_runs(tmp_path):
    storage = _storage(tmp_path, "min", None)
    _run(storage, V3, 0.1, "max", day=3)

    assert _snapshot_delta(storage)["loss"]["goal"] == "min"
    assert _storage_delta(storage)["loss"]["goal"] == "min"


def test_another_runs_declaration_gives_the_goal_when_neither_declares(tmp_path):
    storage = _storage(tmp_path, None, None)
    _run(storage, V3, 0.1, "max", day=3)

    assert _snapshot_delta(storage)["loss"] == {"from": 0.5, "to": 0.3, "goal": "max", "param": False,
                                 "from_policy": None, "to_policy": None}


def test_other_runs_conflicting_goals_give_no_goal_when_neither_declares(tmp_path):
    """The board's resolution (plan 32 follow-up): other runs declaring
    different goals give no goal, not the latest one's."""
    storage = _storage(tmp_path, None, None)
    _run(storage, V3, 0.1, "max", day=3)
    _run(storage, "1.0.0-dev.ggg.hhh", 0.2, "min", day=4)

    delta = _snapshot_delta(storage)["loss"]
    assert delta["goal"] is None and "goal_conflict" not in delta
