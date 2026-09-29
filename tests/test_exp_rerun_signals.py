"""``vmn-exp rerun`` supervises like ``vmn-exp run``: the repo lock is free
while the child lives, and a SIGTERM is forwarded, recorded, and still
removes the workspace."""
import os
import signal
import subprocess
import time

import pytest
from filelock import FileLock, Timeout
from helpers import _PY, _SRC_PATH, _storage
from rerun_helpers import meta, original_run, run_names, worktrees

from vmn_exp.core.status import load_run_state

TIMEOUT = 90


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _start_rerun(app_layout, orig, child, extra_args=()):
    env = dict(os.environ, VMN_WORKING_DIR=app_layout.repo_path, PYTHONPATH=_SRC_PATH)
    env.pop("VMN_LOCK_FILE_PATH", None)
    argv = ["rerun", app_layout.app_name, "-v", orig, *extra_args, "--", _PY, "-c", child]
    return subprocess.Popen(
        [_PY, "-m", "vmn_exp.cli", *argv], cwd=app_layout.repo_path, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )


def _child(marker):
    return f"import time\nopen({marker!r}, 'w').close()\ntime.sleep(60)\n"


def _wait_for_live_rerun(app_layout, orig, marker):
    storage = _storage(app_layout)
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if os.path.exists(marker):
            for verstr in run_names(app_layout):
                state = load_run_state(storage, app_layout.app_name, verstr)
                if meta(app_layout, verstr).get("rerun_of") == orig and state:
                    return verstr, state
        time.sleep(0.2)
    raise AssertionError("the rerun never came up")


def _finish(proc):
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        raise AssertionError("rerun did not exit:\n" + out)
    return out


def test_rerun_supervision_leaves_repo_lock_free(app_layout, tmp_path):
    orig = original_run(app_layout)
    marker = str(tmp_path / "up")
    proc = _start_rerun(app_layout, orig, _child(marker))
    try:
        _wait_for_live_rerun(app_layout, orig, marker)
        lock = FileLock(os.path.join(app_layout.repo_path, ".vmn", "vmn.lock"))
        try:
            lock.acquire(timeout=15)
        except Timeout:
            pytest.fail("the repo lock is held while the rerun's child runs")
        lock.release()
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.communicate()


def test_sigterm_during_rerun_forwards_records_signal_and_cleans_worktree(
    app_layout, tmp_path
):
    orig = original_run(app_layout)
    listed = worktrees(app_layout)
    marker, ws = str(tmp_path / "up"), tmp_path / "ws"
    proc = _start_rerun(app_layout, orig, _child(marker), ["--worktree-dir", str(ws)])
    verstr, _ = _wait_for_live_rerun(app_layout, orig, marker)
    assert ws.exists()

    proc.send_signal(signal.SIGTERM)
    out = _finish(proc)

    assert proc.returncode == 128 + signal.SIGTERM, out
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["signal"] == "SIGTERM"
    assert state["received_signal"] == "SIGTERM"
    assert not ws.exists()
    assert worktrees(app_layout) == listed
