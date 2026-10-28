"""``start_run(on_sigterm="release")``: an evicted pod hands its run back.

A Kubernetes eviction sends SIGTERM; the orchestrator then retries the same
run. Such a run is released (waiting, ``signal: SIGTERM``) instead of failed
with 143, and the process still dies of the signal. Each run follows its own
choice: a default run next to it still fails.
"""
import os
import signal

from exp_helpers import _bootstrap, _storage
from test_sdk_sigterm import _spawn, _terminate, _wait_for_file

from vmn_exp.core.status import CREATED, FAILED, derive_status, load_run_state

_TWO_RUNS = """
import os, time
from vmn_exp.sdk import start_run
handed = start_run(os.environ["APP"], heartbeat_interval_sec=60, on_sigterm="release")
handed.log_metric("loss", 0.5)
ended = start_run(os.environ["APP"], heartbeat_interval_sec=60, nested=True)
with open(os.environ["MARKER"], "w") as f:
    f.write(handed.id + " " + ended.id)
time.sleep(120)
"""


def test_sigterm_releases_a_run_that_asked_for_it(app_layout):
    _bootstrap(app_layout)
    marker = os.path.join(app_layout.base_dir, "opened")
    proc = _spawn(app_layout, _TWO_RUNS, MARKER=marker)
    handed, ended = _wait_for_file(marker, proc).split()

    rc, out = _terminate(proc)

    assert rc == -signal.SIGTERM, out
    storage, app = _storage(app_layout), app_layout.app_name
    state = load_run_state(storage, app, handed)
    assert state["state"] == "released", state
    assert state["signal"] == "SIGTERM" and state["end_reason"] == "released"
    assert state["exit_code"] is None
    assert derive_status(state) == CREATED
    log = storage.load_merged_log(app, handed)
    assert any(e.get("type") == "metrics" and "loss" in e.get("values", {}) for e in log)
    assert derive_status(load_run_state(storage, app, ended)) == FAILED
