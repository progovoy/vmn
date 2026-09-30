"""``vmn-exp run <app> -- cmd`` under ``VMN_MODE=disabled`` just runs *cmd*.

No lock, auto-init, snapshot or run_state: the command replaces vmn-exp
(``execvpe``), so its exit code and signals are its own.
"""
import os
import subprocess
import sys

import pytest
from exp_helpers import _SRC_PATH, _bootstrap, _exp, _storage


@pytest.fixture
def execs(monkeypatch):
    """Record ``os.execvpe`` calls instead of replacing the test process."""
    calls = []
    # The stubbed exec leaves us in the child's cwd; restore it afterwards.
    monkeypatch.chdir(os.getcwd())
    monkeypatch.setattr(os, "execvpe", lambda file, argv, env: calls.append((file, argv, env)))
    monkeypatch.setenv("VMN_MODE", "disabled")
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)
    return calls


def _assert_exec_of(calls, cmd):
    assert len(calls) == 1
    file, argv, env = calls[0]
    assert (file, argv) == (cmd[0], cmd)
    assert env["VMN_METRICS_FILE"] == os.devnull
    assert env["VMN_MODE"] == "disabled"
    assert "VMN_EXPERIMENT_ID" not in env


def test_exp_run_disabled_execs_command_without_recording(app_layout, execs):
    _bootstrap(app_layout)
    cmd = ["python3", "-c", "print('hi')"]

    assert _exp(app_layout.app_name, action="run", run_cmd=cmd) == 0

    _assert_exec_of(execs, cmd)
    assert _storage(app_layout).list_snapshots(app_layout.app_name) == []


def test_exp_run_disabled_needs_no_git_repo(tmp_path, monkeypatch, execs):
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cmd = ["true"]

    assert _exp("app", action="run", run_cmd=cmd) == 0

    _assert_exec_of(execs, cmd)
    assert list(tmp_path.iterdir()) == []


def test_exp_run_disabled_real_child_exit_code(tmp_path):
    env = dict(os.environ, VMN_MODE="disabled", PYTHONPATH=_SRC_PATH)
    env.pop("VMN_WORKING_DIR", None)
    child = [sys.executable, "-c", "import sys; sys.exit(7)"]

    proc = subprocess.run(
        [sys.executable, "-m", "vmn_exp.cli", "run", "app", "--", *child],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )

    assert proc.returncode == 7, proc.stderr
    assert "VMN_MODE=disabled" in proc.stderr
    assert list(tmp_path.iterdir()) == []
