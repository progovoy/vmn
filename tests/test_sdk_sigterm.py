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
import textwrap
import time

import pytest
from helpers import _SRC_PATH, _PY, _bootstrap, _storage

from vmn_exp.core.status import derive_status, load_run_state

JOIN_TIMEOUT = 120


def _env(app_layout, **extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_SRC_PATH, os.environ.get("PYTHONPATH")) if p
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
                content = f.read().strip()
            if content:  # the child creates the file before writing the id
                return content
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


_OPEN_RUN = """
run = start_run(os.environ["APP"], heartbeat_interval_sec=60)
run.log_metric("loss", 0.5)
with open(os.environ["MARKER"], "w") as f:
    f.write(run.id)
time.sleep(120)
"""

_OPEN_AND_WAIT = """
import os, time
from vmn_exp.sdk import start_run
{prelude}
""" + _OPEN_RUN


def test_sigterm_finalizes_the_run_and_the_process_still_dies(app_layout):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    proc = _spawn(app_layout, _OPEN_AND_WAIT.format(prelude=""), MARKER=marker)
    verstr = _wait_for_file(marker, proc)

    rc, out = _terminate(proc)

    assert rc == -signal.SIGTERM, out
    _assert_killed_by_sigterm(app_layout, verstr)
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
    _assert_killed_by_sigterm(app_layout, verstr)


_HANDLER_LIFETIME = """
import os, signal
from vmn_exp.sdk import start_run
installed = signal.getsignal(signal.SIGTERM)
print("AT_IMPORT", installed is not signal.SIG_DFL)
run = start_run(os.environ["APP"])
run.finish()
print("KEPT", signal.getsignal(signal.SIGTERM) is installed)

signal.signal(signal.SIGTERM, signal.SIG_IGN)
with start_run(os.environ["APP"]):
    print("IGNORED_KEPT", signal.getsignal(signal.SIGTERM) is signal.SIG_IGN)
"""


def test_handler_outlives_a_finished_run_and_never_replaces_sig_ign(app_layout):
    # Installed when vmn_exp.sdk is imported on the main thread and kept there:
    # a run a worker thread opens later cannot install it (Python allows no
    # other thread to), so it must already be in place.
    _bootstrap(app_layout)
    proc = _spawn(app_layout, _HANDLER_LIFETIME)
    out, _ = proc.communicate(timeout=JOIN_TIMEOUT)

    assert proc.returncode == 0, out
    assert "AT_IMPORT True" in out
    assert "KEPT True" in out
    # A process that ignores SIGTERM keeps ignoring it: finalizing the run as
    # killed while the process lives on would be a lie.
    assert "IGNORED_KEPT True" in out


_OPEN_ON_A_WORKER_THREAD = """
import os, signal, threading, time
{imports}
{prelude}
def job():
    from vmn_exp.sdk import start_run
""" + textwrap.indent(_OPEN_RUN, "    ") + """

thread = threading.Thread(target=job, daemon=True)
thread.start()
while thread.is_alive():
    thread.join(0.2)
"""


def _assert_killed_by_sigterm(app_layout, verstr):
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["exit_code"] == 128 + signal.SIGTERM, state
    assert state["received_signal"] == "SIGTERM"
    assert state["state"] == "finished"
    assert derive_status(state) == "failed"


def test_a_run_opened_off_the_main_thread_is_finalized_on_sigterm(app_layout):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    script = _OPEN_ON_A_WORKER_THREAD.format(
        imports="import vmn_exp.sdk", prelude=""
    )
    proc = _spawn(app_layout, script, MARKER=marker)
    verstr = _wait_for_file(marker, proc)

    rc, out = _terminate(proc)

    assert rc == -signal.SIGTERM, out
    _assert_killed_by_sigterm(app_layout, verstr)


_HANDLER_AFTER_IMPORT = _USER_HANDLER + "install_signal_handlers()\n"


def test_install_signal_handlers_chains_a_handler_set_after_import(app_layout):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    chained = os.path.join(app_layout.base_dir, "chained")
    script = _OPEN_ON_A_WORKER_THREAD.format(
        imports="from vmn_exp.sdk import install_signal_handlers",
        prelude=_HANDLER_AFTER_IMPORT,
    )
    proc = _spawn(app_layout, script, MARKER=marker, CHAINED=chained)
    verstr = _wait_for_file(marker, proc)

    rc, out = _terminate(proc)

    assert rc == 7, out
    assert os.path.exists(chained), "the workload's own handler never ran"
    _assert_killed_by_sigterm(app_layout, verstr)


def test_sigterm_with_no_open_run_just_kills(app_layout):
    marker = os.path.join(app_layout.base_dir, "ready")
    script = (
        "import os, time, vmn_exp.sdk\n"
        "open(os.environ['MARKER'], 'w').write('x')\n"
        "time.sleep(120)\n"
    )
    proc = _spawn(app_layout, script, MARKER=marker)
    _wait_for_file(marker, proc)

    rc, out = _terminate(proc)

    assert rc == -signal.SIGTERM, out
