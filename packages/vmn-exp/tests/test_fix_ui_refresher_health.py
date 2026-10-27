"""The ui refresher reports each watched index's health without any I/O
(``alive``, ``failing``, ``failures``, ``since_refresh_sec``,
``refreshing_sec``, ``last_error``), and warns once about a refresh that
runs past ``SLOW_REFRESH_SEC``."""
import logging
import threading
import time

import pytest

from vmn_exp.ui.refresher import SLOW_REFRESH_SEC, InlineRefresher, Refresher


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Index:
    app_name = "app"

    def __init__(self, fails=False, gate=None):
        self.refreshes = 0
        self.fails = fails
        self.gate = gate

    def refresh(self):
        if self.gate is not None:
            self.gate.wait(10)
        self.refreshes += 1
        if self.fails:
            raise RuntimeError("storage went away")
        return self

    def snapshot(self):
        return ("snapshot", self.refreshes)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def refresher(clock):
    r = Refresher(interval_sec=60, idle_sec=36000, clock=clock)
    yield r
    r.stop()


def test_a_healthy_index_reports_its_last_refresh(refresher, clock):
    index = _Index()
    refresher.snapshot(index)
    assert _wait_for(lambda: index.refreshes >= 1)
    assert _wait_for(lambda: refresher.health(index)["since_refresh_sec"] is not None)
    clock.now += 30
    assert refresher.health(index) == {
        "alive": True, "failing": False, "failures": 0, "since_refresh_sec": 30.0,
        "refreshing_sec": None, "last_error": None,
    }


def test_a_failing_index_reports_its_streak(refresher, clock):
    index = _Index(fails=True)
    refresher.snapshot(index)
    assert _wait_for(lambda: refresher.health(index)["failing"])
    health = refresher.health(index)
    assert health["failures"] == 1 and health["alive"]
    assert health["last_error"] == "RuntimeError('storage went away')"
    assert health["since_refresh_sec"] is None  # never refreshed


def test_an_unwatched_index_has_no_health(refresher):
    assert refresher.health(_Index()) is None
    assert InlineRefresher().health(_Index()) is None


def test_a_slow_refresh_is_reported_and_warned_about_once(refresher, clock, caplog):
    gate = threading.Event()
    index = _Index(gate=gate)
    refresher.snapshot(index)
    assert _wait_for(lambda: refresher.health(index)["refreshing_sec"] is not None)
    try:
        clock.now += SLOW_REFRESH_SEC + 60
        refresher.snapshot(index)
        refresher.snapshot(index)
        assert refresher.health(index)["refreshing_sec"] == SLOW_REFRESH_SEC + 60
        slow = [r for r in caplog.records
                if r.levelno == logging.WARNING and "running for" in r.getMessage()]
        assert len(slow) == 1 and "app" in slow[0].getMessage()
    finally:
        gate.set()
    assert _wait_for(lambda: refresher.health(index)["refreshing_sec"] is None)
