"""Process-wide SIGTERM defaults and a clean Python exit after the handler.

``VMN_EXP_ON_SIGTERM`` sets ``start_run``'s ``on_sigterm`` for every run that
does not pass one. ``sigterm_exit="raise"`` (or ``VMN_EXP_SIGTERM_EXIT=raise``)
makes the SDK's handler raise ``SystemExit(143)`` in the main thread once the
runs are finalized, instead of re-killing the process, so the workload's
``finally`` blocks and context managers still run.
"""
import os

import pytest
from exp_helpers import _bootstrap, _storage
from test_sdk_sigterm import _spawn, _terminate, _wait_for_file

from vmn_exp.core.status import CREATED, FAILED, derive_status, load_run_state
from vmn_exp.sdk import start_run
from vmn_exp.sdk.context import open_runs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID",
                "VMN_EXP_ON_SIGTERM", "VMN_EXP_SIGTERM_EXIT"):
        monkeypatch.delenv(key, raising=False)


def _opened(app_layout, **kwargs):
    run = start_run(app_layout.app_name, heartbeat_interval_sec=60, **kwargs)
    run.finish()
    return run


def test_on_sigterm_defaults_to_fail_and_kill(app_layout):
    _bootstrap(app_layout)
    run = _opened(app_layout)
    assert (run._on_sigterm, run._sigterm_exit) == ("fail", "kill")


def test_env_sets_the_default_on_sigterm_and_exit(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_EXP_ON_SIGTERM", "release")
    monkeypatch.setenv("VMN_EXP_SIGTERM_EXIT", "raise")
    run = _opened(app_layout)
    assert (run._on_sigterm, run._sigterm_exit) == ("release", "raise")


def test_an_explicit_argument_beats_the_env(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_EXP_ON_SIGTERM", "release")
    monkeypatch.setenv("VMN_EXP_SIGTERM_EXIT", "raise")
    run = _opened(app_layout, on_sigterm="fail", sigterm_exit="kill")
    assert (run._on_sigterm, run._sigterm_exit) == ("fail", "kill")


@pytest.mark.parametrize("env", ["VMN_EXP_ON_SIGTERM", "VMN_EXP_SIGTERM_EXIT"])
def test_an_invalid_env_value_names_the_variable(app_layout, monkeypatch, env):
    _bootstrap(app_layout)
    monkeypatch.setenv(env, "ignore")
    with pytest.raises(ValueError, match=env):
        start_run(app_layout.app_name)
    assert open_runs() == []


def test_sigterm_exit_takes_raise_or_kill_only(app_layout):
    with pytest.raises(ValueError, match="sigterm_exit"):
        start_run(app_layout.app_name, sigterm_exit="exit")


_GUARDED_RUN = """
import os, time
from vmn_exp.sdk import start_run
try:
    with start_run(os.environ["APP"], heartbeat_interval_sec=60, **KWARGS) as run:
        with open(os.environ["MARKER"], "w") as f:
            f.write(run.id)
        time.sleep(120)
finally:
    with open(os.environ["MARKER"] + ".finally", "w") as f:
        f.write("ran")
"""


def _terminated(app_layout, kwargs="{}", **env):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    script = _GUARDED_RUN.replace("**KWARGS", f"**{kwargs}")
    proc = _spawn(app_layout, script, MARKER=marker, **env)
    verstr = _wait_for_file(marker, proc)
    rc, out = _terminate(proc)
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    return rc, out, state, os.path.exists(marker + ".finally")


def test_raise_exits_143_after_finally_blocks_and_releases_per_env(app_layout):
    rc, out, state, finally_ran = _terminated(
        app_layout, VMN_EXP_ON_SIGTERM="release", VMN_EXP_SIGTERM_EXIT="raise")
    assert rc == 143, out
    assert finally_ran, out
    assert state["state"] == "released" and state["signal"] == "SIGTERM", state
    assert derive_status(state) == CREATED


def test_raise_from_the_argument_fails_the_run_with_143(app_layout):
    rc, out, state, finally_ran = _terminated(app_layout, kwargs="{'sigterm_exit': 'raise'}")
    assert rc == 143, out
    assert finally_ran, out
    assert state["exit_code"] == 143 and state["signal"] == "SIGTERM", state
    assert derive_status(state) == FAILED
