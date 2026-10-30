"""``run.detach()``: walk away from a run without writing anything more.

Two pods racing for one run: the loser must stop its threads and let go of the
run while leaving every file the winner writes untouched — no final state, no
release, not even a last heartbeat. Logging on a detached run records nothing,
and neither ``finish()``, the context manager, atexit nor SIGTERM write for it.
"""
import os
import signal
import threading
import time

import pytest

from vmn_exp.sdk import NoOpRun, current_run, run as run_module
from vmn_exp.sdk.background_gate import BackgroundGate
from vmn_exp.sdk.context import open_runs
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.ccccccc"
_RUN_THREADS = ("vmn-heartbeat", "vmn-log-flush", "vmn-exp-sync", "vmn-run-state",
                "vmn-media-upload")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def run(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    run = Run(storage, APP, VERSTR, 0.05, sync_interval_sec=0.05)
    run._open()
    run.log_metric("loss", 1.0, step=1)
    run._log_buffer.flush()
    time.sleep(0.2)  # a few heartbeats and syncs: every thread is up
    yield run
    run.finish()


def _store_files(run):
    files = {}
    for root, _, names in os.walk(run._storage.root):
        for name in names:
            path = os.path.join(root, name)
            stat = os.stat(path)
            files[path] = (stat.st_size, stat.st_mtime_ns)
    return files


def _run_threads():
    return [t.name for t in threading.enumerate() if t.name in _RUN_THREADS]


def test_detach_writes_nothing_even_after_the_heartbeat_interval(run):
    run.log_note("queued, never written")
    before = _store_files(run)
    run.detach()
    time.sleep(1.5)  # many heartbeats and > the 1s log flush interval
    assert _store_files(run) == before


def test_detach_stops_the_runs_threads_and_lets_go_of_it(run):
    assert _run_threads()
    run.detach()
    assert _run_threads() == []
    assert run not in open_runs() and current_run() is None
    assert os.environ.get("VMN_EXPERIMENT_ID") is None


def test_logging_finishing_and_exiting_after_detach_write_nothing(run, tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(run_module, "sync_to_remote", lambda *args: synced.append(args))
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")
    run.detach()
    before = _store_files(run)
    run.log_metric("loss", 0.5)
    run.log_artifact(str(artifact))
    run.log_note("ignored")
    run.set_tags({"k": "v"})
    run.set_intent("ignored")
    run.release()
    run.finish()
    with run:
        pass
    with pytest.raises(ValueError):
        with run:
            raise ValueError("the workload's own error")
    assert _store_files(run) == before
    assert synced == []


def test_atexit_and_sigterm_leave_a_detached_run_alone(run):
    run.detach()
    before = _store_files(run)
    run_module._finalize_signaled(signal.SIGTERM)
    run_module._finalize_open_runs()
    assert _store_files(run) == before


def test_detach_is_idempotent_and_a_no_op_on_a_finished_run(run):
    run.finish()
    before = _store_files(run)
    run.detach()
    run.detach()
    assert _store_files(run) == before


def test_noop_run_detach_is_a_no_op():
    NoOpRun("app").detach()


# -- the gate ----------------------------------------------------------------


def test_a_closed_gate_waits_for_the_call_in_flight_then_runs_none():
    gate, release, calls = BackgroundGate(), threading.Event(), []
    started = threading.Event()

    def chore():
        started.set()
        release.wait(10)
        calls.append("in flight")

    thread = threading.Thread(target=gate.wrap(chore), daemon=True)
    thread.start()
    assert started.wait(5)
    threading.Timer(0.3, release.set).start()

    assert gate.close(timeout=5) is True
    assert calls == ["in flight"]
    assert gate.wrap(lambda: calls.append("late"))() is None
    assert gate.attempt(lambda: calls.append("attempted")) is False
    assert calls == ["in flight"]


def test_a_closed_gate_lets_a_paused_chore_go_without_running_it():
    gate, calls = BackgroundGate(), []
    gate.pause(timeout=1)
    thread = threading.Thread(target=gate.wrap(lambda: calls.append(1)), daemon=True)
    thread.start()
    gate.close(timeout=1)
    thread.join(2)
    assert not thread.is_alive() and calls == []
