"""A refresh that fails is retried later and later (``interval_sec`` doubling
per failure, up to ``MAX_FAILURE_BACKOFF_SEC``), wakes or not, and at the
interval again once one succeeds: a throttling store (S3 ``SlowDown``) was
retried every second, each retry adding to the requests it was refusing."""
import time

import pytest

import vmn_exp.ui.refresher as refresher_module
from vmn_exp.ui.refresher import Refresher


class _Index:
    app_name = "app"

    def __init__(self, failures):
        self.refreshes = 0
        self.failures = failures

    def refresh(self):
        self.refreshes += 1
        if self.refreshes <= self.failures:
            raise RuntimeError("SlowDown")
        return self

    def snapshot(self):
        return ("snapshot", self.refreshes)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def refresher():
    r = Refresher(interval_sec=0.01, idle_sec=60)
    yield r
    r.stop()


def test_failed_refreshes_are_retried_ever_later(refresher):
    index = _Index(failures=1000)
    refresher.snapshot(index)
    time.sleep(0.6)

    # 0.01 s apart that would be ~60; doubling from 0.01 s: 5 retries by 0.31 s.
    assert 2 <= index.refreshes <= 8


def test_wakes_do_not_cut_a_backoff_short(refresher):
    index = _Index(failures=1000)
    refresher.snapshot(index)
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        refresher.wake_all()
        time.sleep(0.002)

    assert index.refreshes <= 8


def test_the_backoff_is_capped(refresher, monkeypatch):
    monkeypatch.setattr(refresher_module, "MAX_FAILURE_BACKOFF_SEC", 0.03)
    index = _Index(failures=1000)
    refresher.snapshot(index)

    assert _wait_for(lambda: index.refreshes >= 20)


def test_a_refresh_that_succeeds_ends_the_backoff(refresher):
    index = _Index(failures=3)
    refresher.snapshot(index)
    assert _wait_for(lambda: index.refreshes > 3)
    after = index.refreshes
    time.sleep(0.3)

    assert index.refreshes - after >= 10
    assert not refresher.health(index)["failing"]


class _FailingJournal:
    scope = "ws"

    def __init__(self):
        self.ticks = 0
        self.watched = set()

    def watch(self, index):
        self.watched.add(index)

    def unwatch(self, index):
        self.watched.discard(index)

    def tick(self):
        self.ticks += 1
        raise RuntimeError("SlowDown")


def test_a_failing_journal_is_ticked_ever_later(refresher):
    journal = _FailingJournal()
    refresher.snapshot(_Index(failures=0), journal)
    time.sleep(0.6)

    assert 2 <= journal.ticks <= 8
