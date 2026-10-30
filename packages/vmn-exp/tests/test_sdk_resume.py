"""``start_run(run_id=...)`` reopens a run a preempted/requeued job left behind.

A requeued job must continue the run it was, not start a new one: same verstr,
running again, heartbeating, and appending to the same log.
"""
import os
import time

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.core.status import RUNNING, derive_status, load_run_state
from vmn_exp.sdk import start_run


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID",
                "VMN_RESUME_REOPEN"):
        monkeypatch.delenv(key, raising=False)


def _state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def _metric_steps(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    # Only the run's own metric: the default-on system metrics carry no step.
    return sorted(
        e["step"] for e in log
        if e.get("type") == "metrics" and "loss" in (e.get("values") or {})
    )


def _preempted_run(app_layout):
    run = start_run(app_layout.app_name)
    run.log_metric("loss", 1.0, step=1)
    run.release(reason="preempted")
    return run


def test_resume_reopens_the_same_run(app_layout):
    _bootstrap(app_layout)
    first = _preempted_run(app_layout)
    started_at = _state(app_layout, first.id)["started_at"]

    resumed = start_run(app_layout.app_name, run_id=first.id, heartbeat_interval_sec=0.05)
    try:
        assert resumed.id == first.id
        state = _state(app_layout, first.id)
        assert state["state"] == "running"
        assert state["exit_code"] is None
        assert state["finished_at"] is None
        assert state["started_at"] == started_at
        assert state["resume_count"] == 1
        assert derive_status(state) == RUNNING

        beat = state["heartbeat"]
        deadline = time.monotonic() + 10
        while _state(app_layout, first.id)["heartbeat"] == beat:
            assert time.monotonic() < deadline, "a resumed run does not heartbeat"
            time.sleep(0.05)

        resumed.log_metric("loss", 0.5, step=2)
    finally:
        resumed.finish()

    assert _state(app_layout, first.id)["exit_code"] == 0
    assert _metric_steps(app_layout, first.id) == [1, 2]
    verstrs = [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]
    assert verstrs == [first.id]


def test_resume_accepts_any_experiment_reference(app_layout):
    _bootstrap(app_layout)
    first = _preempted_run(app_layout)

    with start_run(app_layout.app_name, run_id="latest") as resumed:
        assert resumed.id == first.id
        assert os.environ["VMN_EXPERIMENT_ID"] == first.id


def test_resuming_an_unknown_run_is_an_error(app_layout):
    _bootstrap(app_layout)

    with pytest.raises(ValueError, match="no-such-run"):
        start_run(app_layout.app_name, run_id="no-such-run")


def test_env_fallback_resumes_a_requeued_job_once(app_layout, monkeypatch):
    _bootstrap(app_layout)
    first = _preempted_run(app_layout)
    monkeypatch.setenv("VMN_RESUME_RUN_ID", first.id)

    with start_run(app_layout.app_name) as resumed:
        assert resumed.id == first.id
        # Consumed: a subprocess of the resumed run, or the next run this
        # process opens, must not resume it again.
        assert "VMN_RESUME_RUN_ID" not in os.environ

    with start_run(app_layout.app_name) as fresh:
        assert fresh.id != first.id


def test_explicit_run_id_wins_over_the_env(app_layout, monkeypatch):
    _bootstrap(app_layout)
    first = _preempted_run(app_layout)
    second = _preempted_run(app_layout)
    monkeypatch.setenv("VMN_RESUME_RUN_ID", second.id)

    with start_run(app_layout.app_name, run_id=first.id) as resumed:
        assert resumed.id == first.id


def _finished_run(app_layout):
    run = start_run(app_layout.app_name)
    run.log_metric("loss", 0.1, step=1)
    run.finish()
    return run


def test_reopening_a_finished_run_needs_reopen(app_layout):
    _bootstrap(app_layout)
    done = _finished_run(app_layout)
    before = _state(app_layout, done.id)

    with pytest.raises(ValueError, match="reopen=True") as excinfo:
        start_run(app_layout.app_name, run_id=done.id)

    assert done.id in str(excinfo.value)
    assert _state(app_layout, done.id) == before


def test_reopen_true_reopens_a_finished_run(app_layout):
    _bootstrap(app_layout)
    done = _finished_run(app_layout)

    with start_run(app_layout.app_name, run_id=done.id, reopen=True) as again:
        assert again.id == done.id
        assert _state(app_layout, done.id)["state"] == "running"
        assert _state(app_layout, done.id)["resume_count"] == 1


def test_env_resume_of_a_finished_run_needs_the_reopen_env(app_layout, monkeypatch):
    _bootstrap(app_layout)
    done = _finished_run(app_layout)
    monkeypatch.setenv("VMN_RESUME_RUN_ID", done.id)

    with pytest.raises(ValueError, match="VMN_RESUME_REOPEN=1"):
        start_run(app_layout.app_name)
    assert _state(app_layout, done.id)["exit_code"] == 0


def test_reopen_env_reopens_a_finished_run_once(app_layout, monkeypatch):
    _bootstrap(app_layout)
    done = _finished_run(app_layout)
    monkeypatch.setenv("VMN_RESUME_RUN_ID", done.id)
    monkeypatch.setenv("VMN_RESUME_REOPEN", "1")

    with start_run(app_layout.app_name) as again:
        assert again.id == done.id
        assert "VMN_RESUME_REOPEN" not in os.environ


def test_an_unfinished_run_resumes_without_reopen(app_layout):
    _bootstrap(app_layout)
    run = start_run(app_layout.app_name)
    run.release(reason="preempted")

    with start_run(app_layout.app_name, run_id=run.id) as resumed:
        assert resumed.id == run.id
