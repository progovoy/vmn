"""A report index fed by the workspace's journal follower reads no journal of
its own; unfed (or once its feeder stops) it follows the journal itself."""
import pytest

from vmn_exp.core.journal_reader import JournalReader
from vmn_exp.reports import comments
from vmn_exp.reports import index as rindex
from vmn_exp.reports import store as rstore
from vmn_exp.reports.index import ReportIndex
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.journal_sinks import journal_list_fn
from vmn_exp.storage.local import LocalSnapshotStorage

TARGET = ("run", "trainer", "0.1.0-dev.a")


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def storage(tmp_path, clock):
    return journaled(LocalSnapshotStorage(str(tmp_path / "store"), "runs"), clock=clock)


@pytest.fixture
def own_listings(monkeypatch):
    """Journal listings the report index makes itself."""
    calls = []

    def counting(storage):
        real = journal_list_fn(storage)
        return lambda prefix, start_after=None: (calls.append(prefix), real(prefix, start_after))[1]

    monkeypatch.setattr(rindex, "journal_list_fn", counting)
    return calls


@pytest.fixture
def follower(storage, clock):
    return JournalReader(journal_list_fn(storage), clock)


def _feed(index, follower):
    tick = follower.tick()
    names = {scope: {k.name for k in keys} for scope, keys in tick.entries.items()}
    index.feed(names, tick.overflow, follower.cursor)


def _index(storage, clock, full_sweep_sec=3600):
    return ReportIndex(storage, clock=clock, full_sweep_sec=full_sweep_sec)


def test_a_fed_index_shows_writes_without_listing_the_journal(storage, clock, follower,
                                                              own_listings):
    index = _index(storage, clock)
    index.refresh()
    _feed(index, follower)
    own_listings.clear()
    clock.now += 1
    rid = rstore.create(storage, "New", "")
    comments.add(storage, TARGET, "one")
    _feed(index, follower)
    index.refresh()
    assert [r["rid"] for r in index.reports()] == [rid]
    assert index.comment_counts("trainer") == {"0.1.0-dev.a": {"total": 1, "unresolved": 1}}
    assert own_listings == []


def test_a_first_feed_catches_up_what_the_follower_read_before(storage, clock, follower):
    index = _index(storage, clock)
    index.refresh()
    clock.now += 1
    rid = rstore.create(storage, "Early", "")
    follower.tick()  # consumed before the index was fed
    clock.now += 1
    _feed(index, follower)
    assert [r["rid"] for r in index.reports()] == [rid]


def test_a_feed_before_any_refresh_builds_the_index(storage, clock, follower):
    rid = rstore.create(storage, "T", "")
    index = _index(storage, clock)
    _feed(index, follower)
    assert [r["rid"] for r in index.reports()] == [rid]


def test_an_overflowing_comments_scope_recounts_its_app(storage, clock):
    index = _index(storage, clock)
    index.refresh()
    index.feed({}, set(), None)
    comments.add(storage, TARGET, "one")
    index.feed({}, {("comments", "trainer")}, None)
    assert index.comment_counts("trainer") == {"0.1.0-dev.a": {"total": 1, "unresolved": 1}}


def test_a_stale_feeder_hands_following_back_to_the_index(storage, clock, follower,
                                                          own_listings):
    index = _index(storage, clock)
    _feed(index, follower)
    clock.now += 60
    rid = rstore.create(storage, "Late", "")
    own_listings.clear()
    index.refresh()
    assert [r["rid"] for r in index.reports()] == [rid]
    assert own_listings


def test_a_fed_index_still_rebuilds_every_full_sweep(storage, clock, follower, monkeypatch):
    index = _index(storage, clock, full_sweep_sec=5)
    _feed(index, follower)
    listed = []
    real = rstore.list_reports
    monkeypatch.setattr(rstore, "list_reports", lambda s: listed.append(1) or real(s))
    clock.now += 6
    _feed(index, follower)
    index.refresh()
    assert listed == [1]
