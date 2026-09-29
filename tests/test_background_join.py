"""join_all: wait for several threads under one shared deadline."""
import threading
import time

from vmn_exp.core.background import join_all


def _sleeper(sec):
    thread = threading.Thread(target=time.sleep, args=(sec,), daemon=True)
    thread.start()
    return thread


def test_finished_threads_are_joined():
    threads = [_sleeper(0.05), _sleeper(0.05)]
    join_all(threads, timeout=5)
    assert not any(t.is_alive() for t in threads)


def test_the_timeout_is_shared_not_per_thread():
    threads = [_sleeper(5) for _ in range(4)]
    start = time.monotonic()
    join_all(threads, timeout=0.3)
    assert time.monotonic() - start < 1.0
