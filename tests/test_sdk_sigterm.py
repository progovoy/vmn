"""SIGTERM (a preemption, ``scancel``, a k8s eviction) must finalize SDK runs.

atexit never runs for a process killed by a signal, so a preempted training job
used to be left claiming ``running`` until its heartbeat went stale. The SDK now
finishes its open runs with ``128 + 15`` and then lets the signal do what it
would have done anyway — the process still dies of SIGTERM, and a handler the
workload installed itself still runs.
"""
import os
import signal
import subprocess
import threading
import time

import pytest
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage

from version_stamp.core.experiment_status import load_run_state
from version_stamp.exp import start_run

JOIN_TIMEOUT = 120


def _env(app_layout, **extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_PROJECT_ROOT, os.environ.get("PYTHONPATH")) if p
    )
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env.pop("VMN_EXPERIMENT_ID", None)
    env.pop("VMN_APP_NAME", None)
    env.update(extra)
    return env


def _spawn(app_layout, script, **extra):
    return subprocess.Popen(
        [_PY, "-c", script],
        cwd=app_layout.repo_path,
        env=_env(app_layout, APP=app_layout.app_name, **extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_file(path, proc, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
        if proc.poll() is not None:
            pytest.fail(f"child exited early: {proc.communicate()[0]}")
        time.sleep(0.05)
    proc.kill()
    pytest.fail("child never opened its run")


def _terminate(proc):
    proc.send_signal(signal.SIGTERM)
    try:
        out, _ = proc.communicate(timeout=JOIN_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("the child did not exit after SIGTERM")
    return proc.returncode, out


_OPEN_AND_WAIT = """
import os, time
from version_stamp.exp import start_run
{prelude}
run = start_run(os.environ["APP"], heartbeat_interval_sec=60)
run.log_metric("loss", 0.5)
with open(os.environ["MARKER"], "w") as f:
    f.write(run.id)
time.sleep(120)
"""


def test_sigterm_finalizes_the_run_and_the_process_still_dies(app_layout):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    proc = _spawn(app_layout, _OPEN_AND_WAIT.format(prelude=""), MARKER=marker)
    verstr = _wait_for_file(marker, proc)

    rc, out = _terminate(proc)

    assert rc == -signal.SIGTERM, out
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["state"] == "finished", state
    assert state["exit_code"] == 128 + signal.SIGTERM
    assert state["received_signal"] == "SIGTERM"
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    runs = [e for e in log if e.get("type") == "run"]
    assert runs and runs[-1]["exit_code"] == 143


_USER_HANDLER = """
import signal, sys
def _mine(signum, frame):
    with open(os.environ["CHAINED"], "w") as f:
        f.write("called")
    sys.exit(7)
signal.signal(signal.SIGTERM, _mine)
"""


def test_a_previous_sigterm_handler_is_chained(app_layout):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    chained = os.path.join(app_layout.base_dir, "chained")
    proc = _spawn(
        app_layout,
        _OPEN_AND_WAIT.format(prelude=_USER_HANDLER),
        MARKER=marker,
        CHAINED=chained,
    )
    verstr = _wait_for_file(marker, proc)

    rc, out = _terminate(proc)

    assert rc == 7, out
    assert os.path.exists(chained), "the workload's own handler never ran"
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["exit_code"] == 143


_HANDLER_LIFETIME = """
import os, signal
from version_stamp.exp import start_run
before = signal.getsignal(signal.SIGTERM)
run = start_run(os.environ["APP"])
during = signal.getsignal(signal.SIGTERM)
run.finish()
after = signal.getsignal(signal.SIGTERM)
print("INSTALLED", during is not before)
print("RESTORED", after is before)

signal.signal(signal.SIGTERM, signal.SIG_IGN)
with start_run(os.environ["APP"]):
    print("IGNORED_KEPT", signal.getsignal(signal.SIGTERM) is signal.SIG_IGN)
"""


def test_handler_is_installed_only_while_a_run_is_open(app_layout):
    _bootstrap(app_layout)
    proc = _spawn(app_layout, _HANDLER_LIFETIME)
    out, _ = proc.communicate(timeout=JOIN_TIMEOUT)

    assert proc.returncode == 0, out
    assert "INSTALLED True" in out
    assert "RESTORED True" in out
    # A process that ignores SIGTERM keeps ignoring it: finalizing the run as
    # killed while the process lives on would be a lie.
    assert "IGNORED_KEPT True" in out


def test_a_run_opened_off_the_main_thread_installs_nothing(app_layout):
    _bootstrap(app_layout)
    before = signal.getsignal(signal.SIGTERM)
    seen, errors = [], []

    def worker():
        try:
            with start_run(app_layout.app_name):
                seen.append(signal.getsignal(signal.SIGTERM))
        except Exception as exc:  # surfaced below
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=JOIN_TIMEOUT)

    assert not errors, errors
    assert seen == [before]
