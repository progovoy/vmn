"""The ui refresher heals itself: an error in any step of a refresh cycle
(the snapshot, the GIL hint, a refresh listener, the warming hook) never ends
its loop, one listener's error never keeps the others from hearing, and a
refresh or journal thread that died anyway is restarted by the next request."""
import logging
import time

import pytest

from vmn_exp.ui.refresher import Refresher


class _Index:
    app_name = "app"

    def __init__(self, snapshot_fails=False):
        self.refreshes = 0
        self.snapshot_fails = snapshot_fails

    def refresh(self):
        self.refreshes += 1
        return self

    def snapshot(self):
        if self.snapshot_fails and self.refreshes:
            raise RuntimeError("snapshot broke")
        return ("snapshot", self.refreshes)


class _Journal:
    scope = "ws"

    def __init__(self, fail_once):
        self.ticks = 0
        self.watched = set()
        self._fail_once = fail_once

    def watch(self, index):
        self.watched.add(index)

    def unwatch(self, index):
        self.watched.discard(index)

    def tick(self):
        self.ticks += 1
        if self.ticks == 1:
            raise self._fail_once


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def refresher():
    r = Refresher(interval_sec=0.02, idle_sec=60)
    yield r
    r.stop()


def _raise(*_):
    raise RuntimeError("listener broke")


def test_a_raising_listener_never_ends_the_loop_nor_silences_the_others(refresher, caplog):
    heard = []
    refresher.add_listener(_raise)
    refresher.add_listener(lambda index, snap: heard.append(snap))
    index = _Index()
    refresher.snapshot(index)
    assert _wait_for(lambda: len(heard) >= 3)
    assert refresher.watching(index)
    assert any(r.levelno >= logging.WARNING and r.exc_info for r in caplog.records)


def test_a_raising_snapshot_never_ends_the_loop(refresher):
    index = _Index(snapshot_fails=True)
    refresher.snapshot(index)
    assert _wait_for(lambda: index.refreshes >= 5)
    assert refresher.watching(index)


def test_a_raising_gil_hint_never_ends_the_loop(refresher, monkeypatch):
    monkeypatch.setattr(refresher.gil_hint, "note", _raise)
    index = _Index()
    refresher.snapshot(index)
    assert _wait_for(lambda: index.refreshes >= 5)
    assert refresher.watching(index)


def test_a_raising_warming_hook_never_ends_the_loop():
    refresher = Refresher(interval_sec=0.02, idle_sec=60, on_refresh=_raise)
    try:
        index = _Index()
        refresher.snapshot(index)
        assert _wait_for(lambda: index.refreshes >= 5)
        assert refresher.watching(index)
    finally:
        refresher.stop()


def test_a_dead_refresh_thread_is_logged_and_restarted_by_the_next_request(refresher, caplog):
    calls = []

    def exits_once(index, snap):
        calls.append(snap)
        if len(calls) == 1:
            raise SystemExit("a listener called sys.exit")

    refresher.add_listener(exits_once)
    index = _Index()
    refresher.snapshot(index)
    assert _wait_for(lambda: not refresher.watching(index))
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)
    before = index.refreshes

    refresher.snapshot(index)

    assert refresher.watching(index)
    assert _wait_for(lambda: index.refreshes > before + 2)
    assert any(r.levelno == logging.ERROR and "restart" in r.getMessage()
               for r in caplog.records)


def test_a_dead_journal_thread_is_restarted_by_the_next_request(refresher, caplog):
    journal, index = _Journal(SystemExit("tick called sys.exit")), _Index()
    refresher.snapshot(index, journal)
    assert _wait_for(lambda: not refresher._journals[journal].is_alive())
    assert journal.ticks == 1

    refresher.snapshot(index, journal)

    assert _wait_for(lambda: journal.ticks >= 3)
    assert any(r.levelno == logging.ERROR and "restart" in r.getMessage()
               for r in caplog.records)


def test_a_failing_journal_keeps_ticking(refresher):
    journal, index = _Journal(RuntimeError("journal unreadable")), _Index()
    refresher.snapshot(index, journal)
    assert _wait_for(lambda: journal.ticks >= 3)
