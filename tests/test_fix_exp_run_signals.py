"""`vmn exp run` forwards termination signals and always records the outcome.

Slurm, Kubernetes eviction and spot preemption send SIGTERM to the supervisor.
It used to die on the spot, orphaning the child and leaving the run claiming
``running`` until it read ``stuck``. A preempted run must read ``failed``, with
the signal on record, and the child must not outlive its supervisor.
"""

import os
import signal
import subprocess
import time

from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage

from version_stamp.core import experiment_status as st
from version_stamp.core.experiment_status import load_run_state

TIMEOUT = 90


def _env(app_layout, extra=None):
    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _PROJECT_ROOT
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_LOCK_FILE_PATH"):
        env.pop(key, None)
    env.update(extra or {})
    return env


def _start_supervisor(app_layout, child_script, env_extra=None):
    # `-m version_stamp.cli` exits with main()'s code, exactly like the `vmn`
    # console script (entry.py's own __main__ collapses it to 0/1).
    return subprocess.Popen(
        [
            _PY,
            "-m",
            "version_stamp.cli",
            "exp",
            "run",
            app_layout.app_name,
            "--",
            _PY,
            "-c",
            child_script,
        ],
        cwd=app_layout.repo_path,
        env=_env(app_layout, env_extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # No controlling terminal: a signal the test sends reaches the
        # supervisor alone, never the child through a foreground group.
        start_new_session=True,
    )


def _wait_for_live_run(app_layout, marker):
    """The verstr and run state of the supervised run, once its child is up.

    ``marker`` is a file the child creates once it has installed its own
    signal handlers, so the test never races the child's startup.
    """
    storage = _storage(app_layout)
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if os.path.exists(marker):
            for meta in storage.list_snapshots(app_layout.app_name):
                state = load_run_state(storage, app_layout.app_name, meta["verstr"])
                if state and state.get("pid"):
                    return meta["verstr"], state
        time.sleep(0.2)
    raise AssertionError("the supervised run never came up")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _child(marker, body):
    return (
        "import os, signal, sys, time\n"
        f"{body}\n"
        f"open({marker!r}, 'w').close()\n"
        "time.sleep(60)\n"
    )


def _finish(proc):
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        raise AssertionError("supervisor did not exit:\n" + out)
    return out


def _final(app_layout, verstr):
    storage = _storage(app_layout)
    return (
        load_run_state(storage, app_layout.app_name, verstr),
        storage.load_merged_log(app_layout.app_name, verstr),
    )


def test_sigterm_is_forwarded_and_the_run_is_recorded_failed(app_layout, tmp_path):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    proc = _start_supervisor(app_layout, _child(marker, ""))
    verstr, live = _wait_for_live_run(app_layout, marker)

    proc.send_signal(signal.SIGTERM)
    out = _finish(proc)

    assert proc.returncode == 128 + signal.SIGTERM, out
    assert not _alive(live["pid"]), "the child outlived its supervisor"
    state, log = _final(app_layout, verstr)
    assert state["state"] == "finished"
    assert state["exit_code"] == 128 + signal.SIGTERM
    assert state["signal"] == "SIGTERM"
    assert state["received_signal"] == "SIGTERM"
    assert st.derive_status(state) == st.FAILED
    assert [e for e in log if e["type"] == "run"][-1]["exit_code"] == state["exit_code"]


def test_child_that_handles_sigterm_gracefully_keeps_its_exit_code_and_metrics(
    app_layout, tmp_path
):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    body = (
        "def _bye(*_):\n"
        "    open(os.environ['VMN_METRICS_FILE'], 'a').write('saved=1\\n')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, _bye)"
    )
    proc = _start_supervisor(app_layout, _child(marker, body))
    verstr, _ = _wait_for_live_run(app_layout, marker)

    proc.send_signal(signal.SIGTERM)
    out = _finish(proc)

    assert proc.returncode == 0, out
    state, log = _final(app_layout, verstr)
    assert state["exit_code"] == 0
    assert state["received_signal"] == "SIGTERM"
    assert "signal" not in state
    assert any(e.get("values", {}).get("saved") == 1.0 for e in log)


def test_child_ignoring_sigterm_is_killed_after_the_grace_period(app_layout, tmp_path):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    body = "signal.signal(signal.SIGTERM, signal.SIG_IGN)"
    proc = _start_supervisor(
        app_layout, _child(marker, body), {"VMN_EXP_KILL_GRACE_SEC": "2"}
    )
    verstr, live = _wait_for_live_run(app_layout, marker)

    started = time.time()
    proc.send_signal(signal.SIGTERM)
    _finish(proc)

    assert time.time() - started < 30
    assert not _alive(live["pid"])
    state, _ = _final(app_layout, verstr)
    assert state["exit_code"] == 128 + signal.SIGKILL
    assert state["signal"] == "SIGKILL"
    assert st.derive_status(state) == st.FAILED


def test_sigint_sent_to_the_supervisor_alone_reaches_the_child(app_layout, tmp_path):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    proc = _start_supervisor(app_layout, _child(marker, ""))
    verstr, live = _wait_for_live_run(app_layout, marker)

    proc.send_signal(signal.SIGINT)
    _finish(proc)

    assert not _alive(live["pid"])
    state, _ = _final(app_layout, verstr)
    assert state["received_signal"] == "SIGINT"
    assert state["exit_code"] not in (None, 0)
    assert st.derive_status(state) == st.FAILED


def test_child_killed_by_a_signal_records_the_shell_exit_code(app_layout, capfd):
    from helpers import _experiment, extract_dev_verstr

    _bootstrap(app_layout)
    capfd.readouterr()
    code = _experiment(
        app_layout.app_name,
        action="run",
        run_cmd=[_PY, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)

    assert code == 128 + signal.SIGTERM
    state, _ = _final(app_layout, verstr)
    assert state["exit_code"] == 128 + signal.SIGTERM
    assert state["signal"] == "SIGTERM"
    assert "received_signal" not in state
