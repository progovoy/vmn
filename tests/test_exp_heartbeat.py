"""The periodic publisher behind an in-process experiment run.

`vmn exp run` refreshes a run's heartbeat from its supervising poll loop. An
SDK run has no supervisor, so it carries its own thread — and if that thread
stops silently, every SDK run decays into `stuck` while still training. These
tests pin the failure modes that would cause that.
"""
import threading
import time

import pytest

from version_stamp.exp.heartbeat import Heartbeat

TICK = 0.02


def _counter():
    calls = []
    lock = threading.Lock()

    def publish():
        with lock:
            calls.append(time.monotonic())

    return calls, publish


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(TICK / 4)
    return False


def test_publishes_repeatedly_while_running():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    hb.start()
    try:
        assert _wait_for(lambda: len(calls) >= 3), calls
    finally:
        hb.stop()


def test_does_not_publish_before_start():
    calls, publish = _counter()
    Heartbeat(publish, interval_sec=TICK)
    time.sleep(TICK * 3)
    assert calls == []


def test_stop_halts_publishing():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    hb.start()
    assert _wait_for(lambda: len(calls) >= 1)
    hb.stop()
    settled = len(calls)
    time.sleep(TICK * 5)
    assert len(calls) == settled, "published after stop()"


def test_stop_is_idempotent_and_safe_before_start():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    hb.stop()  # never started
    hb.start()
    hb.stop()
    hb.stop()  # twice
    assert not hb.alive


def test_start_twice_does_not_spawn_a_second_thread():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    before = threading.active_count()
    hb.start()
    hb.start()
    try:
        assert threading.active_count() == before + 1
    finally:
        hb.stop()


def test_stop_returns_promptly_even_with_a_long_interval():
    """stop() must not block for a full interval — runs would hang on exit."""
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=30)
    hb.start()
    started = time.monotonic()
    hb.stop()
    assert time.monotonic() - started < 2.0
    assert not hb.alive


def test_a_raising_publisher_does_not_kill_the_heartbeat():
    """A transient S3 error must not silently end the run's liveness."""
    calls = []

    def publish():
        calls.append(1)
        raise RuntimeError("transient storage failure")

    hb = Heartbeat(publish, interval_sec=TICK)
    hb.start()
    try:
        assert _wait_for(lambda: len(calls) >= 3), calls
        assert hb.alive
    finally:
        hb.stop()


def test_thread_is_a_daemon_so_it_cannot_wedge_interpreter_exit():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    hb.start()
    try:
        assert hb._thread.daemon is True
    finally:
        hb.stop()


def test_alive_reflects_lifecycle():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    assert not hb.alive
    hb.start()
    assert hb.alive
    hb.stop()
    assert not hb.alive


def test_interval_must_be_positive():
    calls, publish = _counter()
    with pytest.raises(ValueError):
        Heartbeat(publish, interval_sec=0)
    with pytest.raises(ValueError):
        Heartbeat(publish, interval_sec=-1)


def test_context_manager_starts_and_stops():
    calls, publish = _counter()
    hb = Heartbeat(publish, interval_sec=TICK)
    with hb:
        assert _wait_for(lambda: len(calls) >= 1)
    assert not hb.alive
    settled = len(calls)
    time.sleep(TICK * 5)
    assert len(calls) == settled
