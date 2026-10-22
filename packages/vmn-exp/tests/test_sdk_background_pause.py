"""``run.pause_background()`` quiesces every background thread of a run.

A process that forks (a fork-pool simulator, DataLoader workers) must not fork
while one of the run's threads is mid S3 call: the child inherits the held
pool/logging locks and can deadlock. Pausing waits for the call in flight and
keeps the heartbeat, the log flusher, the remote sync and the media uploader
from starting another until resumed.
"""
import threading
import time

import pytest

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.sdk import NoOpRun, background_paused, pause_background, resume_background
from vmn_exp.sdk.background_gate import BackgroundGate
from vmn_exp.sdk.run import Run

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.ccccccc"


class _CountingStorage(CachedSnapshotStorage):
    def __init__(self, root):
        super().__init__(LocalSnapshotStorage(root, area="runs"))
        self.log_writes = 0

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        self.log_writes += 1
        return super().append_log_entries(app_name, verstr, writer_id, entries)


@pytest.fixture
def run(tmp_path):
    storage = _CountingStorage(str(tmp_path))
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    run = Run(storage, APP, VERSTR, 0.1)
    run._open()
    yield run
    run.finish()


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# -- the gate ----------------------------------------------------------------


def _start_blocking_chore(gate, release):
    started = threading.Event()

    def chore():
        started.set()
        release.wait(10)

    thread = threading.Thread(target=gate.wrap(chore), daemon=True)
    thread.start()
    assert started.wait(5)
    return thread


def test_pause_waits_for_the_call_in_flight():
    gate, release = BackgroundGate(), threading.Event()
    thread = _start_blocking_chore(gate, release)
    threading.Timer(0.3, release.set).start()

    began = time.monotonic()
    assert gate.pause(timeout=5) is True
    assert time.monotonic() - began >= 0.25
    thread.join(1)
    assert not thread.is_alive()
    gate.resume()


def test_pause_gives_up_after_its_timeout():
    gate, release = BackgroundGate(), threading.Event()
    _start_blocking_chore(gate, release)

    began = time.monotonic()
    assert gate.pause(timeout=0.2) is False
    assert time.monotonic() - began < 2
    release.set()
    gate.resume()


def test_a_chore_does_not_start_while_paused():
    gate, calls = BackgroundGate(), []
    assert gate.pause(timeout=1) is True
    thread = threading.Thread(target=gate.wrap(lambda: calls.append(1)), daemon=True)
    thread.start()
    time.sleep(0.2)
    assert calls == []
    gate.resume()
    thread.join(2)
    assert calls == [1]


def test_pauses_nest():
    gate, calls = BackgroundGate(), []
    gate.pause(timeout=1)
    gate.pause(timeout=1)
    thread = threading.Thread(target=gate.wrap(lambda: calls.append(1)), daemon=True)
    thread.start()
    gate.resume()
    time.sleep(0.2)
    assert calls == []
    gate.resume()
    thread.join(2)
    assert calls == [1]


def test_attempt_skips_while_paused_and_runs_otherwise():
    gate, calls = BackgroundGate(), []
    assert gate.attempt(lambda: calls.append(1)) is True
    gate.pause(timeout=1)
    assert gate.attempt(lambda: calls.append(2)) is False
    gate.resume()
    assert calls == [1]


def test_pausing_from_inside_a_chore_does_not_wait_for_itself():
    gate, results = BackgroundGate(), []
    gate.wrap(lambda: results.append(gate.pause(timeout=5)))()
    assert results == [True]
    gate.resume()


def test_a_nested_chore_on_a_busy_thread_runs_while_paused():
    gate, calls = BackgroundGate(), []

    def outer():
        gate.pause(timeout=1)
        gate.wrap(lambda: calls.append("inner"))()
        gate.resume()

    gate.wrap(outer)()
    assert calls == ["inner"]


# -- a run -------------------------------------------------------------------


def test_nothing_is_written_in_the_background_while_paused(run):
    assert run.pause_background(timeout=5) is True
    before = run._storage.log_writes
    run.log_note("queued while paused")
    time.sleep(1.5)  # > the 1s flush interval and many 0.1s heartbeats
    assert run._storage.log_writes == before

    run.resume_background()
    assert _wait_for(lambda: run._storage.log_writes > before)


def test_the_context_manager_resumes_on_exit(run):
    with run.background_paused() as quiesced:
        assert quiesced is True
        before = run._storage.log_writes
        run.log_note("queued while paused")
        time.sleep(1.5)
        assert run._storage.log_writes == before
    assert _wait_for(lambda: run._storage.log_writes > before)


def test_module_helpers_pause_every_open_run(run):
    assert pause_background(timeout=5) is True
    before = run._storage.log_writes
    run.log_note("queued while paused")
    time.sleep(1.5)
    assert run._storage.log_writes == before
    resume_background()
    assert _wait_for(lambda: run._storage.log_writes > before)

    with background_paused() as quiesced:
        assert quiesced is True


def test_finish_while_paused_still_records_everything(run):
    run.pause_background(timeout=5)
    run.log_note("logged before finish")
    began = time.monotonic()
    run.finish()
    assert time.monotonic() - began < 5
    log = LocalSnapshotStorage(run._storage._local.root, "runs").load_merged_log(APP, VERSTR)
    assert any(e.get("text") == "logged before finish" for e in log)


def test_noop_run_pause_is_a_no_op():
    run = NoOpRun("app")
    assert run.pause_background(timeout=1) is True
    run.resume_background()
    with run.background_paused() as quiesced:
        assert quiesced is True
