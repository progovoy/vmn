"""A traced lock is a drop-in ``threading.Lock``/``RLock`` that remembers who
holds it, who waits on it and since when, so a diagnostic dump can name the
thread every request is queued behind without reading raw stacks."""
import gc
import threading
import time
import uuid

import pytest

from vmn_exp.core.traced_lock import TracedLock, locks_section


def _name():
    return f"test lock {uuid.uuid4().hex[:8]}"


def _held(name):
    return [h for h in locks_section()["held"] if h["name"] == name]


def _stats(name):
    return next(s for s in locks_section()["stats"] if s["name"] == name)


def _hold(lock, name="holder"):
    """Hold *lock* on a thread *name* until the returned event is set."""
    acquired, release = threading.Event(), threading.Event()

    def hold():
        with lock:
            acquired.set()
            release.wait(10)

    thread = threading.Thread(target=hold, name=name, daemon=True)
    thread.start()
    assert acquired.wait(5)
    return release, thread


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_it_excludes_like_a_lock():
    lock = TracedLock(_name())
    assert lock.acquire()
    assert lock.locked()
    assert lock.acquire(blocking=False) is False
    assert lock.acquire(timeout=0.01) is False
    lock.release()
    assert not lock.locked()
    with lock:
        assert lock.locked()
    with pytest.raises(RuntimeError):
        lock.release()


def test_a_reentrant_one_reenters_and_releases_on_the_last_exit():
    lock = TracedLock(_name(), reentrant=True)
    with lock:
        with lock:
            assert lock.locked()
        assert lock.locked()
        other = []
        thread = threading.Thread(target=lambda: other.append(lock.acquire(blocking=False)))
        thread.start()
        thread.join(5)
        assert other == [False]
    assert not lock.locked()
    with pytest.raises(RuntimeError):
        lock.release()


def test_a_reentrant_one_backs_a_condition():
    cond = threading.Condition(TracedLock(_name(), reentrant=True))
    ready = []

    def produce():
        with cond:
            ready.append(1)
            cond.notify_all()

    with cond:
        with cond:  # nested, as an RLock allows
            threading.Thread(target=produce, daemon=True).start()
            assert cond.wait_for(lambda: ready, 5)


def test_a_plain_one_backs_a_condition():
    cond = threading.Condition(TracedLock(_name()))
    with cond:
        assert cond.wait(0.01) is False
    with pytest.raises(RuntimeError):
        cond.notify()


def test_the_section_names_the_holder_and_its_waiters_longest_held_first():
    old, new = _name(), _name()
    old_lock, new_lock = TracedLock(old), TracedLock(new)
    release_old, holder_old = _hold(old_lock, "old-holder")
    time.sleep(0.05)
    release_new, holder_new = _hold(new_lock, "new-holder")
    waiter = threading.Thread(target=lambda: old_lock.acquire() and old_lock.release(),
                              name="queued-request", daemon=True)
    waiter.start()
    try:
        assert _wait_until(lambda: _held(old) and _held(old)[0]["waiters"])
        held = [h for h in locks_section()["held"] if h["name"] in (old, new)]
        assert [h["name"] for h in held] == [old, new]
        assert held[0]["holder"] == "old-holder"
        assert held[0]["held_sec"] >= held[1]["held_sec"] >= 0
        assert [w["thread"] for w in held[0]["waiters"]] == ["queued-request"]
        assert held[0]["waiters"][0]["waiting_sec"] >= 0
        assert held[1]["waiters"] == []
    finally:
        release_old.set()
        release_new.set()
        for t in (holder_old, holder_new, waiter):
            t.join(5)
    assert _held(old) == [] and _held(new) == []


def test_reading_the_section_never_waits_on_a_held_lock():
    name = _name()
    release, holder = _hold(TracedLock(name))
    try:
        done = []
        reader = threading.Thread(target=lambda: done.append(locks_section()), daemon=True)
        reader.start()
        reader.join(2)
        assert done and _held(name)
    finally:
        release.set()
        holder.join(5)


def test_stats_count_acquires_contention_and_the_longest_wait_and_hold():
    name = _name()
    lock = TracedLock(name)
    with lock:
        pass
    release, holder = _hold(lock)
    waiter = threading.Thread(target=lambda: lock.acquire() and lock.release(), daemon=True)
    waiter.start()
    assert _wait_until(lambda: _held(name)[0]["waiters"])
    time.sleep(0.05)
    release.set()
    holder.join(5)
    waiter.join(5)
    stats = _stats(name)
    assert stats["acquires"] == 3
    assert stats["contended"] == 1
    assert stats["max_wait_sec"] >= 0.04
    assert stats["max_held_sec"] >= 0.04


def test_a_reentrant_acquire_is_not_counted_again():
    name = _name()
    lock = TracedLock(name, reentrant=True)
    with lock:
        with lock:
            pass
    assert _stats(name)["acquires"] == 1


def test_locks_of_one_name_merge_their_stats():
    name = _name()
    for _ in range(3):
        with TracedLock(name):
            pass
    assert [s["acquires"] for s in locks_section()["stats"] if s["name"] == name] == [3]


def test_a_dropped_lock_leaves_the_registry():
    name = _name()
    lock = TracedLock(name)
    lock.acquire()
    assert _held(name)
    del lock
    gc.collect()
    assert _held(name) == []
