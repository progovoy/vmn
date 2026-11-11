"""Sweep trials whose command calls ``start_run()``: the script records into
the trial run itself, so the trial is its own metric source and the median
rule reads its points (plan 38 A12). Real git."""
import pytest

from exp_helpers import _SRC_PATH, _storage
from test_sweep_cli import _status, _trials, _vmn_exp
from test_sweep_sdk_trials import _sdk_sweep
from vmn_exp.core.status import load_run_state
from vmn_exp.core.sweep.summary import trial_rows


@pytest.fixture(autouse=True)
def _sdk_child_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SWEEP_PARAMS", "VMN_EXP_ADOPT",
                "VMN_EXP_ADOPT_RUN_ID", "VMN_EXP_ADOPT_PID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PYTHONPATH", _SRC_PATH)  # the trial imports vmn_exp.sdk


def test_trial_metric_is_the_trial_runs_own_and_metric_source_is_the_trial(
        app_layout, tmp_path, capsys):
    sweep = _sdk_sweep(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0

    trials = _trials(app_layout, sweep)
    assert len(trials) == 3 and all("loss" in t["metrics"] for t in trials)
    assert not any(r.get("parent") in {t["verstr"] for t in trials}
                   for r in _storage(app_layout).list_snapshots(app_layout.app_name))
    spec = _storage(app_layout).load_metadata(app_layout.app_name, sweep)["sweep"]
    rows = trial_rows(_storage(app_layout), app_layout.app_name, sweep, spec)
    assert all(r["metric_source"] == r["verstr"] for r in rows)
    assert _status(app_layout, sweep, capsys)["best"]["verstr"] == trials[1]["verstr"]


def test_early_stop_reads_the_adopted_trials_points(app_layout, tmp_path, capsys):
    sweep = _sdk_sweep(
        app_layout, tmp_path, capsys,
        parameters={"x": {"values": [0, 1, 10]}},
        early_terminate={"type": "median", "min_iter": 2, "check_interval_sec": 0.2},
    )
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0

    fast0, _, slow = _trials(app_layout, sweep)
    assert fast0["end_reason"] is None and slow["end_reason"] == "stopped"
    state = load_run_state(_storage(app_layout), app_layout.app_name, slow["verstr"])
    assert state["duration_sec"] < 10  # 60 steps * 0.25s had it run out
