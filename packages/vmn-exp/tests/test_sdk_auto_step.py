"""The auto-incrementing step: ``log_metrics`` without ``step=`` records
``run.step`` and advances it (one per-run counter with a high-water mark)."""
import threading
import time
from types import SimpleNamespace

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.sdk import start_run, sysmetrics
from vmn_exp.sdk.autolog import _log_final_metrics, _log_metric_series
from vmn_exp.sdk.ranks import NoOpRun


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID", "VMN_MODE"):
        monkeypatch.delenv(key, raising=False)


def _metric_entries(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [e for e in log if e.get("type") == "metrics"]


def _steps(app_layout, verstr, key):
    return [
        e.get("step") for e in _metric_entries(app_layout, verstr)
        if key in (e.get("values") or {})
    ]


def _quiet_run(app_layout, **kwargs):
    return start_run(app_layout.app_name, system_metrics=False, **kwargs)


def test_log_metrics_without_step_records_0_1_2(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        for value in (1.0, 0.5, 0.25):
            run.log_metric("loss", value)
    assert _steps(app_layout, run.id, "loss") == [0, 1, 2]


def test_one_call_shares_one_step_for_all_keys(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        run.log_metrics({"loss": 1.0, "acc": 0.1})
        run.log_metrics({"loss": 0.5, "acc": 0.2})
    assert _steps(app_layout, run.id, "loss") == [0, 1]
    assert _steps(app_layout, run.id, "acc") == [0, 1]


def test_explicit_step_raises_the_high_water_mark(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        run.log_metric("loss", 1.0, step=10)
        run.log_metric("loss", 0.5)
    assert _steps(app_layout, run.id, "loss") == [10, 11]


def test_explicit_lower_step_is_kept_and_does_not_rewind_counter(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        run.log_metric("loss", 1.0, step=5)
        run.log_metric("loss", 0.9, step=2)
        run.log_metric("loss", 0.5)
    assert _steps(app_layout, run.id, "loss") == [5, 2, 6]


def test_all_dropped_values_consume_no_step(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        run.log_metric("loss", 1.0)
        run.log_metric("loss", "not a number")
        run.log_metric("loss", 0.5)
    assert _steps(app_layout, run.id, "loss") == [0, 1]


def test_commit_false_shares_the_next_committed_step(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        run.log_metric("acc", 0.1, commit=False)
        assert run.step == 0
        run.log_metrics({"loss": 1.0})
        run.log_metric("loss", 0.5)
    assert _steps(app_layout, run.id, "acc") == [0]
    assert _steps(app_layout, run.id, "loss") == [0, 1]


def test_system_metrics_carry_no_step_and_consume_none(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setattr(sysmetrics, "build_collector", lambda pid=None: lambda: {"sys_cpu_percent": 1.0})
    with start_run(app_layout.app_name, heartbeat_interval_sec=0.1, system_metrics=True) as run:
        time.sleep(0.8)
        run.log_metric("loss", 1.0)
    sys_steps = _steps(app_layout, run.id, "sys_cpu_percent")
    assert sys_steps and all(step is None for step in sys_steps)
    assert _steps(app_layout, run.id, "loss") == [0]


def test_concurrent_log_metrics_yield_unique_steps(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        def worker():
            for _ in range(50):
                run.log_metric("loss", 1.0)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert sorted(_steps(app_layout, run.id, "loss")) == list(range(200))


def test_resume_continues_after_last_logged_step(app_layout):
    _bootstrap(app_layout)
    first = _quiet_run(app_layout)
    first.log_metric("loss", 1.0)
    first.log_metric("loss", 0.9, step=7)
    first.finish(exit_code=143)

    with _quiet_run(app_layout, run_id=first.id) as resumed:
        assert resumed.step == 8
        resumed.log_metric("loss", 0.5)
    assert _steps(app_layout, first.id, "loss") == [0, 7, 8]


def test_resume_ignores_rewound_steps(app_layout):
    _bootstrap(app_layout)
    first = _quiet_run(app_layout)
    for _ in range(5):
        first.log_metric("loss", 1.0)
    first.finish(exit_code=143)
    with _quiet_run(app_layout, run_id=first.id, rewind_to_step=1) as rewound:
        assert rewound.step == 2
        rewound.log_metric("loss", 0.1)
    rewound.finish()

    with _quiet_run(app_layout, run_id=first.id) as resumed:
        assert resumed.step == 3


def test_fork_continues_from_start_step(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as source:
        for _ in range(4):
            source.log_metric("loss", 1.0)

    with _quiet_run(app_layout, fork_from=source.id, fork_step=1) as fork:
        assert fork.step == fork.start_step == 2
        fork.log_metric("loss", 0.1)
    assert _steps(app_layout, fork.id, "loss") == [0, 1, 2]


def test_run_step_property_reports_next_step(app_layout):
    _bootstrap(app_layout)
    with _quiet_run(app_layout) as run:
        assert run.step == 0
        run.log_metric("loss", 1.0)
        assert run.step == 1
        run.log_metric("loss", 1.0, step=4)
        assert run.step == 5


def test_autolog_series_steps_unchanged(app_layout):
    _bootstrap(app_layout)
    adapter = SimpleNamespace(
        label="fake",
        series=lambda call: {"loss": [1.0, 0.5, 0.25]},
        metrics=lambda call: {"score": 0.9},
    )
    with _quiet_run(app_layout) as run:
        _log_metric_series(run, adapter, None)
        _log_final_metrics(run, adapter, None)
    assert _steps(app_layout, run.id, "fake_loss") == [0, 1, 2]
    assert _steps(app_layout, run.id, "fake_score") == [3]


def test_noop_run_step_counts():
    run = NoOpRun("app")
    assert run.step == 0
    run.log_metric("loss", 1.0)
    run.log_metrics({"loss": 1.0}, commit=False)
    assert run.step == 1
    run.log_metrics({"loss": 1.0}, step=9)
    assert run.step == 10
