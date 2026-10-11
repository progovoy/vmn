"""A local-first cache's merge rewrites the local copy of a writer's log
(read, merge with the remote's lines, replace), so an append must not land
while one runs: it would be dropped when the rewrite's replace lands. An
ordinary append waits for the rewrite however long it takes; only while the
SDK's SIGTERM finalizer runs (``finalizing()``) does an append give up
waiting after ``LOCAL_LOCK_WAIT_SEC`` — the rewrite may be the main thread's,
frozen where the signal caught it."""
import signal
import threading

import pytest
import yaml
from frozen_holders import finishes_within, frozen_in, in_thread
from s3_helpers import cached_host, meta
from test_storage_cached_log_seed import (  # noqa: F401
    APP,
    V,
    W,
    _append,
    _bucket,
    _remote_texts,
    _texts,
)
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.sdk import run as sdk_run
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage import cached_log_merge
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.cached_log_merge import finalizing

WAIT_SEC = 0.5
PROMPT_SEC = 2 * WAIT_SEC + 3
APPENDED = ["a0", "a1", "b0", "late"]


@pytest.fixture(autouse=True)
def _short_wait(monkeypatch):
    monkeypatch.setattr(cached_log_merge, "LOCAL_LOCK_WAIT_SEC", WAIT_SEC)


def _frozen_seed(tmp_path):
    """Host b's first append under W seeds its local log from the remote's
    (a0, a1) and is frozen inside that rewrite, before its replace lands."""
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    _append(a, "a0", 0)
    _append(a, "a1", 1)
    a.sync_log_to_remote(APP, V, W)
    b = cached_host(tmp_path, "b")
    assert b.load_record(APP, V)[0] is not None
    entered, release = frozen_in(b._local, "save_file")
    seeder = in_thread(lambda: _append(b, "b0", 2))
    assert entered.wait(5)
    return b, release, seeder


def _appending(call):
    done = threading.Event()
    in_thread(lambda: (call(), done.set()))
    return done


def test_an_append_waits_for_a_rewrite_of_the_local_log(tmp_path):
    b, release, seeder = _frozen_seed(tmp_path)

    done = _appending(lambda: _append(b, "late", 3))
    waited = not done.wait(PROMPT_SEC)
    release.set()
    seeder.join(10)

    assert waited, "the append went on while a merge rewrote the local log"
    assert done.wait(10)
    assert sorted(_texts(b)) == APPENDED
    b.sync_log_to_remote(APP, V, W)
    assert sorted(_remote_texts()) == APPENDED


def _finalizer_append(host, text, second):
    with finalizing():
        _append(host, text, second)


def test_the_finalizer_does_not_wait_on_a_frozen_rewrite(tmp_path):
    b, release, seeder = _frozen_seed(tmp_path)

    finished, took = finishes_within(PROMPT_SEC, lambda: _finalizer_append(b, "final", 3))
    release.set()
    seeder.join(10)

    assert finished, f"the finalizer's append waited {took:.1f}s on the frozen rewrite"


def test_appends_wait_again_once_the_finalizer_is_done(tmp_path):
    with finalizing():
        pass
    b, release, seeder = _frozen_seed(tmp_path)

    done = _appending(lambda: _append(b, "late", 3))
    waited = not done.wait(PROMPT_SEC)
    release.set()
    seeder.join(10)

    assert waited and done.wait(10)


def test_the_sigterm_finalizer_records_a_run_whose_main_thread_froze_mid_rewrite(tmp_path):
    storage = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    storage.save(APP, V, meta(V), {})
    run = Run(storage, APP, V, 60)
    run._open()
    run.log_note("before")
    run._log_buffer.flush()
    held, release = threading.Event(), threading.Event()

    def frozen_rewrite():
        with storage._local_log_held(rewrite=True):
            held.set()
            release.wait(60)

    holder = in_thread(frozen_rewrite)
    assert held.wait(5)

    finished, took = finishes_within(
        PROMPT_SEC + 5, lambda: sdk_run._finalize_signaled(signal.SIGTERM))
    release.set()
    holder.join(10)

    assert finished, f"finalizing waited {took:.1f}s on the frozen rewrite"
    state = yaml.safe_load(storage.load_file(APP, V, RUN_STATE_FILE))
    assert state["state"] == "finished" and state["exit_code"] == 128 + signal.SIGTERM
    log = storage.load_merged_log(APP, V)
    assert [e["exit_code"] for e in log if e["type"] == "run"] == [128 + signal.SIGTERM]
