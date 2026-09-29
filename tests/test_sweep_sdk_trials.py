"""Trials that log through the SDK: ``start_run()`` inside the trial nests a run
under it, and the sweep reads the target metric from that nested run."""
import textwrap

import pytest

from helpers import _SRC_PATH, _storage
from test_sweep_cli import _create, _status, _trials, _vmn_exp
from vmn_exp.core.status import load_run_state

SDK_TRAIN = textwrap.dedent(
    """
    import time
    from vmn_exp.sdk import start_run, sweep_params
    x = sweep_params()["x"]
    slow = x >= 10
    with start_run(snapshot=False) as run:
        for step in range(1, (60 if slow else 4) + 1):
            run.log_metric("loss", x + 1.0 / step, step=step)
            time.sleep(0.25 if slow else 0.0)
    """
)


@pytest.fixture(autouse=True)
def _sdk_child_env(monkeypatch, tmp_path):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SWEEP_PARAMS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PYTHONPATH", _SRC_PATH)  # the trial imports vmn_exp.sdk


def _sdk_sweep(app_layout, tmp_path, capsys, **overrides):
    sweep = _create(app_layout, tmp_path, capsys, **overrides)
    (tmp_path / "train.py").write_text(SDK_TRAIN)  # replaces the metrics-file script
    return sweep


def test_status_best_comes_from_the_trials_nested_sdk_run(app_layout, tmp_path, capsys):
    sweep = _sdk_sweep(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0

    trials = _trials(app_layout, sweep)
    assert len(trials) == 3
    assert all("loss" not in t["metrics"] for t in trials)  # it lives one level down
    status = _status(app_layout, sweep, capsys)
    assert status["best"]["params"] == {"x": 1}
    assert status["best"]["value"] == pytest.approx(1.25)
    assert status["best"]["verstr"] == trials[1]["verstr"]


def test_median_rule_reads_the_nested_sdk_runs_series(app_layout, tmp_path, capsys):
    sweep = _sdk_sweep(
        app_layout, tmp_path, capsys,
        parameters={"x": {"values": [0, 1, 10]}},
        early_terminate={"type": "median", "min_iter": 2, "check_interval_sec": 0.2},
    )
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0

    fast0, fast1, slow = _trials(app_layout, sweep)
    assert "stopped_early" not in fast0["tags"]
    assert slow["tags"]["stopped_early"] == "true"
    state = load_run_state(_storage(app_layout), app_layout.app_name, slow["verstr"])
    assert state["stopped_early"] is True
    assert state["duration_sec"] < 10  # 60 steps * 0.25s had it run out
