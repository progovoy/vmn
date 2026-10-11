"""An exception landing right after a local-first cache took its local log
lock — a signal handler's KeyboardInterrupt, before the holder reached its
``try`` — never leaves the lock held: later appends and rewrites get it."""
import pytest
from frozen_holders import finishes_within
from s3_helpers import meta
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage import cached_log_merge
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.cached_log_merge import LocalLogLock

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
WAIT_SEC = 0.5
PROMPT_SEC = 2 * WAIT_SEC + 3


@pytest.fixture(autouse=True)
def _short_wait(monkeypatch):
    monkeypatch.setattr(cached_log_merge, "LOCAL_LOCK_WAIT_SEC", WAIT_SEC)


def _storage(tmp_path):
    storage = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    storage.save(APP, V, meta(V), {})
    return storage


def _interrupted_right_after_taking_it(monkeypatch):
    """The lock is taken, then a KeyboardInterrupt lands before its holder
    gets back control."""
    real = LocalLogLock._enter

    def taken_then_interrupted(self, *args, **kwargs):
        assert real(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(LocalLogLock, "_enter", taken_then_interrupted)


def _rewrite_then_append(storage):
    with storage._local_log_held(rewrite=True):
        pass
    with storage._local_log_held():
        pass
    note = {"timestamp": "2026-01-01T00:00:01Z", "type": "note", "text": "after"}
    assert storage.append_log_entry(APP, V, "w", note)


@pytest.mark.parametrize("rewrite", [True, False], ids=["rewrite", "append"])
def test_an_interrupt_right_after_taking_the_local_log_lock_releases_it(
        tmp_path, monkeypatch, rewrite):
    storage = _storage(tmp_path)
    with monkeypatch.context() as patched:
        _interrupted_right_after_taking_it(patched)
        with pytest.raises(KeyboardInterrupt):
            with storage._local_log_held(rewrite=rewrite):
                pytest.fail("the holder's block ran")

    finished, took = finishes_within(PROMPT_SEC, lambda: _rewrite_then_append(storage))

    assert finished, f"the lock stayed held: waited {took:.1f}s"
    assert [e["text"] for e in storage.load_merged_log(APP, V) if e["type"] == "note"] == ["after"]


def test_an_interrupted_append_inside_its_block_releases_the_lock_too(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        with storage._local_log_held():
            raise KeyboardInterrupt

    finished, took = finishes_within(PROMPT_SEC, lambda: _rewrite_then_append(storage))

    assert finished, f"the lock stayed held: waited {took:.1f}s"
