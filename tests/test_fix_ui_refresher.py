"""The ui's background refresher: watched indexes are kept fresh off the
request path, idle ones stop, and a failing refresh keeps the last snapshot."""
import threading
import time

import pytest

from version_stamp.ui.refresher import Refresher


class FakeIndex:
    """What the refresher needs of an ExperimentIndex: snapshot() and refresh()."""

    def __init__(self, fail_after=None, first_load_sec=0.0):
        self.refreshes = 0
        self.generation = 0
        self._fail_after = fail_after
        self._first_load_sec = first_load_sec
        self._snapshot = None
        self._lock = threading.Lock()

    def refresh(self):
        with self._lock:
            if self._snapshot is None and self._first_load_sec:
                time.sleep(self._first_load_sec)
            self.refreshes += 1
            if self._fail_after is not None and self.refreshes > self._fail_after:
                raise RuntimeError("storage went away")
            self.generation += 1
            self._snapshot = ("snapshot", self.generation)
        return self

    def snapshot(self):
        if self._snapshot is None:
            self.refresh()
        return self._snapshot


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def refresher():
    r = Refresher(interval_sec=0.02, idle_sec=0.3)
    yield r
    r.stop()


def test_the_first_request_waits_for_the_initial_load(refresher):
    index = FakeIndex(first_load_sec=0.1)
    snap = refresher.snapshot(index)
    assert snap is not None and snap[0] == "snapshot"


def test_a_watched_index_is_refreshed_without_requests(refresher):
    index = FakeIndex()
    refresher.snapshot(index)
    assert _wait_for(lambda: index.refreshes >= 5)
    assert refresher.snapshot(index)[1] >= 5


def test_an_idle_index_stops_refreshing(refresher):
    index = FakeIndex()
    refresher.snapshot(index)
    assert _wait_for(lambda: not refresher.watching(index))
    settled = index.refreshes
    time.sleep(0.1)
    assert index.refreshes == settled


def test_a_request_after_idle_restarts_the_refresher(refresher):
    index = FakeIndex()
    refresher.snapshot(index)
    assert _wait_for(lambda: not refresher.watching(index))
    before = index.refreshes

    refresher.snapshot(index)

    assert refresher.watching(index)
    assert _wait_for(lambda: index.refreshes > before)


def test_a_failing_refresh_keeps_serving_the_last_snapshot(refresher, caplog):
    index = FakeIndex(fail_after=2)
    refresher.snapshot(index)
    assert _wait_for(lambda: index.refreshes >= 6)

    assert refresher.snapshot(index) == ("snapshot", 2)
    assert refresher.watching(index)  # errors never kill the thread
    assert any("refresh" in r.getMessage().lower() for r in caplog.records)


def test_stop_ends_every_thread():
    r = Refresher(interval_sec=0.02, idle_sec=60)
    indexes = [FakeIndex(), FakeIndex()]
    for index in indexes:
        r.snapshot(index)
    r.stop()
    assert not any(r.watching(index) for index in indexes)


# ---- InlineRefresher: the same interface, refreshing on the request path ----


class StaleIndex(FakeIndex):
    def refresh_if_stale(self, max_age_sec):
        assert max_age_sec == 0
        return self.refresh().snapshot()


def test_inline_refresher_refreshes_before_every_snapshot():
    from version_stamp.ui.refresher import InlineRefresher

    index = StaleIndex()
    inline = InlineRefresher()
    assert inline.snapshot(index) == ("snapshot", 1)
    assert inline.snapshot(index) == ("snapshot", 2)
    assert not inline.background and Refresher().background


def test_inline_refresher_keeps_the_full_sweep_default():
    from version_stamp.ui.refresher import InlineRefresher

    assert InlineRefresher().full_sweep_sec is None
    assert Refresher().full_sweep_sec == 30


def test_create_app_refreshes_inline_unless_asked_otherwise(tmp_path):
    pytest.importorskip("fastapi")
    from version_stamp.ui.refresher import InlineRefresher
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    app = create_app(WorkspaceManager(str(tmp_path / "data")))
    assert isinstance(app.state.refresher, InlineRefresher)
