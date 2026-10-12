"""The SIGTERM finalizer records a run even though the main thread was caught
in the middle of a log append: it runs on a worker thread while the main
thread sits in the signal handler, so it must not wait on a lock that thread
holds (see vmn_exp.storage.ship_state.FINALIZING_WAIT_SEC)."""
import yaml
from frozen_holders import finishes_within, frozen_in, in_thread
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.writer import get_writer_id
from vmn_exp.sdk import run as sdk_run
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.ship_state import FINALIZING_WAIT_SEC

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"
# The periodic flush and the final one may each wait out the lock once.
PROMPT_SEC = 2 * FINALIZING_WAIT_SEC + 5


def _storage(tmp_path):
    storage = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return storage


def _note(text):
    return {"timestamp": "2026-01-01T00:00:01Z", "type": "note", "text": text}


def test_the_sigterm_finalizer_records_a_run_whose_append_was_interrupted(tmp_path):
    storage = _storage(tmp_path)
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    run.log_note("before")
    run._log_buffer.flush()  # the frozen append below is the next storage append
    entered, release = frozen_in(storage._local, "append_log_entries")
    holder = in_thread(
        lambda: storage.append_log_entry(APP, VERSTR, get_writer_id(), _note("interrupted")))
    assert entered.wait(5)

    finished, took = finishes_within(
        PROMPT_SEC, lambda: sdk_run._finalize_open_runs(143, received_signal="SIGTERM"))
    release.set()
    holder.join(10)

    assert finished, f"finalizing waited {took:.1f}s on the interrupted append"
    state = yaml.safe_load(storage.load_file(APP, VERSTR, RUN_STATE_FILE))
    assert state["state"] == "finished" and state["exit_code"] == 143
    log = storage.load_merged_log(APP, VERSTR)
    assert [e["text"] for e in log if e["type"] == "note"].count("before") == 1
    assert [e["exit_code"] for e in log if e["type"] == "run"] == [143]
