"""Warming after a refresh runs on its own worker, never on the refresh
thread: a slow warm (a 486k-run board) must not hold back publishing the
next snapshot, and a busy warmer skips to the newest generation instead of
queueing every one it missed."""
import threading

from test_fix_ui_refresher import FakeIndex, _wait_for
from vmn_exp.ui.latest_worker import LatestWorker
from vmn_exp.ui.refresher import Refresher


def test_a_blocked_warm_never_holds_back_publishing():
    release, calls, threads = threading.Event(), [], []

    def warm(snapshot):
        calls.append(snapshot)
        threads.append(threading.current_thread().name)
        release.wait(5)

    refresher = Refresher(interval_sec=0.01, idle_sec=5, on_refresh=warm)
    index = FakeIndex()
    try:
        refresher.snapshot(index)
        assert _wait_for(lambda: calls)
        assert _wait_for(lambda: index.refreshes >= 6)
        assert len(calls) == 1  # still warming the first, the rest published meanwhile
    finally:
        release.set()
        refresher.stop()
    assert threads[0] == "vmn-ui-warm"


def test_after_a_blocked_warm_the_newest_snapshot_is_warmed():
    release, calls = threading.Event(), []

    def warm(snapshot):
        calls.append(snapshot)
        release.wait(5)

    refresher = Refresher(interval_sec=0.01, idle_sec=5, on_refresh=warm)
    index = FakeIndex()
    try:
        refresher.snapshot(index)
        assert _wait_for(lambda: index.refreshes >= 6)
        release.set()
        assert _wait_for(lambda: len(calls) >= 2)
        assert calls[1][1] >= 6  # skipped to the newest, not the second refresh
    finally:
        release.set()
        refresher.stop()


def test_a_busy_worker_coalesces_to_the_latest_value():
    started, release, runs = threading.Event(), threading.Event(), []

    def work(value):
        runs.append(value)
        started.set()
        release.wait(5)

    worker = LatestWorker(work, name="vmn-test-latest")
    try:
        worker.submit("app", 1)
        assert started.wait(5)
        for value in range(2, 6):
            worker.submit("app", value)
        release.set()
        assert _wait_for(lambda: runs[-1] == 5)
        assert worker.idle(timeout=5)
    finally:
        worker.stop()
    assert runs == [1, 5]


def test_each_key_keeps_its_own_latest_value():
    started, release, runs = threading.Event(), threading.Event(), []

    def work(value):
        runs.append(value)
        started.set()
        release.wait(5)

    worker = LatestWorker(work, name="vmn-test-latest")
    try:
        worker.submit("a", "a1")
        assert started.wait(5)
        worker.submit("b", "b1")
        worker.submit("a", "a2")
        worker.submit("b", "b2")
        release.set()
        assert _wait_for(lambda: len(runs) == 3)
        assert worker.idle(timeout=5)
    finally:
        worker.stop()
    assert runs == ["a1", "b2", "a2"]


def test_a_failing_work_keeps_the_worker_going():
    runs = []

    def work(value):
        runs.append(value)
        raise RuntimeError("warm failed")

    worker = LatestWorker(work, name="vmn-test-latest")
    try:
        worker.submit("app", 1)
        assert _wait_for(lambda: runs == [1])
        worker.submit("app", 2)
        assert _wait_for(lambda: runs == [1, 2])
    finally:
        worker.stop()
