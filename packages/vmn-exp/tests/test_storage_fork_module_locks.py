"""Module state a forked child must not inherit: the metric seal lock, the
ship-state locks and flags, the store marker's lock, and a marker root's
object-store client. The pid change is simulated, so no process forks here."""
import os
import threading
import types
from contextlib import ExitStack

import pytest


@pytest.fixture
def forked(monkeypatch):
    """Call it to make this process look like a forked child of itself."""
    real = os.getpid()
    return lambda: monkeypatch.setattr(os, "getpid", lambda: real + 1)


def _finishes(fn, timeout=2):
    done = threading.Event()

    def run():
        fn()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    return done.wait(timeout)


def _held_by_another_thread(lock):
    """*lock* taken by a parent thread that keeps it; returns its release."""
    taken, release = threading.Event(), threading.Event()

    def hold():
        with lock:
            taken.set()
            release.wait(10)

    threading.Thread(target=hold, daemon=True).start()
    assert taken.wait(2)
    return release.set


def test_the_seal_lock_a_parent_thread_held_does_not_block_the_child(forked, monkeypatch):
    from vmn_exp.core import metric_compact

    release = _held_by_another_thread(metric_compact._SEAL_LOCK)
    try:
        forked()
        storage = types.SimpleNamespace()
        assert _finishes(lambda: metric_compact.note_points(storage, "app", "v", "w", 1)), \
            "the child blocked on the parent's seal lock"
    finally:
        monkeypatch.undo()
        release()


def test_the_ship_state_guard_a_parent_thread_held_does_not_block_the_child(
        forked, monkeypatch, tmp_path):
    from vmn_exp.storage import ship_state

    release = _held_by_another_thread(ship_state._THREAD_LOCKS_GUARD)
    try:
        forked()
        assert _finishes(lambda: ship_state._thread_lock(str(tmp_path / "x"))), \
            "the child blocked on the parent's lock guard"
    finally:
        monkeypatch.undo()
        release()


def test_a_record_lock_a_parent_thread_held_is_free_in_the_child(forked, monkeypatch, tmp_path):
    from vmn_exp.storage import ship_state

    monkeypatch.setattr(ship_state, "LOCK_WAIT_SEC", 0.5)
    record = str(tmp_path)
    path = os.path.join(record, ship_state.SHIP_DIR, "lock")
    release = _held_by_another_thread(ship_state._thread_lock(path))
    try:
        forked()

        def take():
            with ship_state.ship_lock(record):
                pass

        assert _finishes(take), "the child waited on the parent thread's record lock"
    finally:
        monkeypatch.undo()
        release()


def test_a_hold_the_forking_thread_had_does_not_skip_the_childs_file_lock(
        forked, monkeypatch, tmp_path):
    from vmn_exp.storage import ship_state

    record, real = str(tmp_path), os.getpid()
    taken = []
    real_lock_file = ship_state._lock_file
    monkeypatch.setattr(ship_state, "_lock_file",
                        lambda path, name: taken.append(os.getpid()) or real_lock_file(path, name))
    with ExitStack() as parent:
        parent.enter_context(ship_state.ship_lock(record))
        forked()
        with ship_state.ship_lock(record):
            pass
        monkeypatch.undo()  # the parent gives its hold back
    assert taken == [real, real + 1], "the child trusted the parent's hold depth"


def test_the_child_is_not_finalizing_because_the_parent_was(forked, monkeypatch):
    from vmn_exp.storage import ship_state

    with ship_state.finalizing():
        forked()
        assert not ship_state.is_finalizing()
        assert ship_state._wait_sec() == ship_state.LOCK_WAIT_SEC
        monkeypatch.undo()
    assert not ship_state.is_finalizing()


def test_the_store_marker_lock_a_parent_thread_held_does_not_block_the_child(
        forked, monkeypatch):
    from vmn_exp.storage import store_marker

    release = _held_by_another_thread(store_marker._lock)
    try:
        forked()
        assert _finishes(store_marker.forget_checked), \
            "the child blocked on the parent's marker lock"
    finally:
        monkeypatch.undo()
        release()


def test_a_marker_root_built_in_the_parent_uses_the_childs_client(forked):
    from vmn_exp.storage.s3_base import S3Base
    from vmn_exp.storage.store_marker import root_of

    class Client:
        pass

    store = S3Base("bkt", prefix="team/runs", client_factory=Client)
    root = root_of(store)
    parent = root.client
    assert parent is store._s3
    forked()
    assert root.client is store._s3 and root.client is not parent
    assert root.key == ("object", "Client", None, "bkt", "team")
