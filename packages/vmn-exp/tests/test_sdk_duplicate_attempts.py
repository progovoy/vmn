"""Two attempts of one run (speculative duplicates, a resumed pod next to a
live one): once one attempt finishes the run, the other attempt's heartbeats
must not flip ``run_state.yml`` back to running.

A legit resume of a finished run (``start_run(run_id=...)``) still reopens it:
its start is always written, and its own heartbeats keep the run running.
"""
import time

import pytest
from exp_helpers import _bootstrap, _storage
from s3_helpers import cached_host, meta, mocked_bucket, s3_storage

from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import start_run
from vmn_exp.sdk.run import Run

APP = "app"
X = "0.0.1-dev.abc1234.0000001"
BEAT = 0.05


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


def _wait_for_beats(state_of, beats=5):
    """Let a heartbeat of BEAT seconds tick *beats* times."""
    time.sleep(BEAT * beats + 0.3)
    return state_of()


def test_a_duplicate_attempt_does_not_reopen_a_run_another_attempt_finished(
    app_layout,
):
    _bootstrap(app_layout)
    app = app_layout.app_name
    winner = start_run(app, heartbeat_interval_sec=3600)
    loser = start_run(app, run_id=winner.id, heartbeat_interval_sec=BEAT)
    try:
        winner.finish(exit_code=0)

        state = _wait_for_beats(
            lambda: load_run_state(_storage(app_layout), app, winner.id)
        )
        assert state["state"] == "finished"
        assert state["exit_code"] == 0
    finally:
        loser.finish()


@pytest.fixture
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _open(host, prior_state=None):
    run = Run(host, APP, X, BEAT, prior_state=prior_state)
    run._open()
    return run


def _remote_state():
    return load_run_state(s3_storage(), APP, X)


def _wait_until_remote_written_by(run, timeout=10):
    """Until *run*'s own heartbeat has reached the remote (under load its
    first upload can take longer than a few beats)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _remote_state() or {}
        if state.get("attempt") == run._state["attempt"] and state.get("heartbeat_seq", 0) > 1:
            return
        time.sleep(BEAT)
    raise AssertionError("the duplicate's heartbeat never reached the remote")


def test_a_duplicate_on_another_host_does_not_reopen_the_finished_run(
    tmp_path, _bucket
):
    host_a, host_b = cached_host(tmp_path, "a"), cached_host(tmp_path, "b")
    assert host_a.create_exclusive(APP, X, meta(X), {})
    loser = _open(host_b, prior_state={})
    winner = Run(host_a, APP, X, 3600)
    winner._open()
    try:
        _wait_until_remote_written_by(loser)
        winner.finish(exit_code=0)

        state = _wait_for_beats(_remote_state)
        assert state["state"] == "finished"
        assert state["exit_code"] == 0
    finally:
        loser.finish()


def test_resuming_a_finished_run_on_another_host_keeps_it_running(tmp_path, _bucket):
    host_a, host_b = cached_host(tmp_path, "a"), cached_host(tmp_path, "b")
    assert host_a.create_exclusive(APP, X, meta(X), {})
    first = Run(host_a, APP, X, 3600)
    first._open()
    first.finish(exit_code=143)

    resumed = _open(host_b, prior_state=_remote_state())
    try:
        state = _wait_for_beats(_remote_state)
        assert state["state"] == "running"
        assert state["exit_code"] is None
        assert state["heartbeat_seq"] > 1
    finally:
        resumed.finish()
    assert _remote_state()["exit_code"] == 0
