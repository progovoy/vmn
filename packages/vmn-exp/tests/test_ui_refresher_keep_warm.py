"""Keep-warm: a watched index keeps refreshing while the server runs, nobody
asking. Default: on for a store workspace's (journal-driven) indexes, off
for a checkout's; ``keep_warm=True``/``False`` forces either way."""
import time

import pytest

from test_fix_ui_refresher import FakeIndex, _wait_for
from vmn_exp.ui.refresher import Refresher


class FakeJournal:
    """What the refresher needs of a WorkspaceJournal."""

    scope = "ws"

    def __init__(self):
        self.watched = set()
        self.ticks = 0

    def watch(self, index):
        self.watched.add(index)

    def unwatch(self, index):
        self.watched.discard(index)

    def tick(self):
        self.ticks += 1


def _refresher(**kw):
    return Refresher(interval_sec=0.02, idle_sec=0.2, **kw)


@pytest.fixture
def stops():
    made = []
    yield made
    for r in made:
        r.stop()


def _idle_past(refresher, index, sec=0.5):
    """*index*'s refreshes over *sec* seconds, well past ``idle_sec``."""
    time.sleep(sec)
    before = index.refreshes
    time.sleep(0.15)
    return index.refreshes - before


def test_a_store_index_keeps_refreshing_unwatched_by_default(stops):
    refresher, index, journal = _refresher(), FakeIndex(), FakeJournal()
    stops.append(refresher)
    refresher.snapshot(index, journal)

    assert _idle_past(refresher, index) > 0
    assert refresher.watching(index)
    assert index in journal.watched  # still hinted by the journal


def test_a_checkout_index_idles_by_default(stops):
    refresher, index = _refresher(), FakeIndex()
    stops.append(refresher)
    refresher.snapshot(index)

    assert _wait_for(lambda: not refresher.watching(index))


def test_keep_warm_on_keeps_a_checkout_index_refreshing(stops):
    refresher, index = _refresher(keep_warm=True), FakeIndex()
    stops.append(refresher)
    refresher.snapshot(index)

    assert _idle_past(refresher, index) > 0
    assert refresher.watching(index)


def test_keep_warm_off_lets_a_store_index_idle(stops):
    refresher, index, journal = _refresher(keep_warm=False), FakeIndex(), FakeJournal()
    stops.append(refresher)
    refresher.snapshot(index, journal)

    assert _wait_for(lambda: not refresher.watching(index))
    assert index not in journal.watched


def test_stop_ends_a_kept_warm_index():
    refresher, index = _refresher(keep_warm=True), FakeIndex()
    refresher.snapshot(index, FakeJournal())
    refresher.stop()
    assert not refresher.watching(index)


def test_each_watch_says_whether_it_is_kept_warm(stops):
    refresher = _refresher()
    stops.append(refresher)
    store, checkout = FakeIndex(), FakeIndex()
    refresher.snapshot(store, FakeJournal())
    refresher.snapshot(checkout)

    watches = dict(refresher.watched())
    assert watches[store].keep_warm is True
    assert watches[checkout].keep_warm is False
