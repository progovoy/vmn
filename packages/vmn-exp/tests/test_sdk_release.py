"""``run.release()`` hands a run back unfinished (plan 28 API2, decision D2).

An evicted pod's orchestrator retries the same run, so the pod must stop
recording without ending it: the log is flushed and synced, the heartbeat
stops, and ``run_state.yml`` says ``state: released`` with no exit code, so
the run derives as ``created`` (waiting) at once instead of ``running`` until
it goes ``stuck``. ``start_run(run_id=...)`` reopens it, counting the attempt.
"""
import time

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.core.status import CREATED, RUNNING, SUCCEEDED, derive_status, load_run_state
from vmn_exp.sdk import current_run, run as run_module, start_run
from vmn_exp.sdk.context import open_runs
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.sdk.reader import list_runs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


def _state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def _released_run(app_layout, **kwargs):
    run = start_run(app_layout.app_name, heartbeat_interval_sec=0.05)
    run.log_metric("loss", 1.0, step=1)
    run.release(**kwargs)
    return run


def test_a_released_run_is_waiting_and_closed_here(app_layout):
    _bootstrap(app_layout)
    run = _released_run(app_layout, reason="evicted")

    state = _state(app_layout, run.id)
    assert state["state"] == "released"
    assert state["exit_code"] is None and state["finished_at"] is None
    assert state["end_reason"] == "released"
    assert state["release_reason"] == "evicted"
    assert state["released_at"]
    assert "signal" not in state
    assert derive_status(state) == CREATED
    assert run not in open_runs() and current_run() is None

    log = _storage(app_layout).load_merged_log(app_layout.app_name, run.id)
    assert any(e.get("type") == "metrics" and "loss" in e.get("values", {}) for e in log)
    assert not [e for e in log if e.get("type") == "run"]  # it did not end


def test_a_released_run_stops_heartbeating(app_layout):
    _bootstrap(app_layout)
    run = _released_run(app_layout)
    beat = _state(app_layout, run.id)["heartbeat_seq"]
    time.sleep(0.3)
    assert _state(app_layout, run.id)["heartbeat_seq"] == beat
    assert _state(app_layout, run.id)["state"] == "released"


def test_release_is_idempotent_and_finish_after_it_changes_nothing(app_layout):
    _bootstrap(app_layout)
    run = _released_run(app_layout)
    first = _state(app_layout, run.id)
    run.release()
    run.finish()
    assert _state(app_layout, run.id) == first


def test_atexit_leaves_a_released_run_alone(app_layout):
    _bootstrap(app_layout)
    run = _released_run(app_layout)
    run_module._finalize_open_runs()
    assert derive_status(_state(app_layout, run.id)) == CREATED


def test_reopening_a_released_run_counts_the_attempt(app_layout):
    _bootstrap(app_layout)
    first = _released_run(app_layout)
    released_at = _state(app_layout, first.id)["released_at"]

    resumed = start_run(app_layout.app_name, run_id=first.id)
    state = _state(app_layout, first.id)
    assert derive_status(state) == RUNNING
    assert state["resume_count"] == 1
    assert state.get("end_reason") is None
    # The last release stays on record: an eviction wave outlives its retries.
    assert state["released_at"] == released_at
    resumed.log_metric("loss", 0.5, step=2)
    resumed.finish()

    state = _state(app_layout, first.id)
    assert derive_status(state) == SUCCEEDED and state["resume_count"] == 1
    log = _storage(app_layout).load_merged_log(app_layout.app_name, first.id)
    steps = sorted(e["step"] for e in log
                   if e.get("type") == "metrics" and "loss" in (e.get("values") or {}))
    assert steps == [1, 2]


def test_released_and_retried_runs_are_queryable(app_layout):
    _bootstrap(app_layout)
    waiting = _released_run(app_layout)
    retried = _released_run(app_layout)
    start_run(app_layout.app_name, run_id=retried.id).finish()
    app = app_layout.app_name

    def ids(query):
        return [r["verstr"] for r in list_runs(app, query=query, use_index=False)]

    assert ids('end_reason = "released"') == [waiting.id]
    assert ids('status = "succeeded" and resume_count > 0') == [retried.id]
    assert set(ids("released_at != null")) == {waiting.id, retried.id}
    rows = {r["verstr"]: r for r in list_runs(app, use_index=False)}
    assert rows[waiting.id]["status"] == CREATED
    assert rows[waiting.id]["released_at"] == _state(app_layout, waiting.id)["released_at"]


def test_on_sigterm_takes_fail_or_release_only(app_layout):
    with pytest.raises(ValueError, match="on_sigterm"):
        start_run(app_layout.app_name, on_sigterm="ignore")


def test_a_noop_run_releases_nothing():
    assert NoOpRun("app").release(reason="x") is None
