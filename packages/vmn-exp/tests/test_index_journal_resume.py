"""A journaled index persists how far into the change journal its records
are (its journal mark): a restart replays the journal from there instead of
listing every record, and falls back to a full listing — run behind serving,
journal-discovered runs still publishing — only once the journal no longer
holds the entries since the mark."""
import pytest

from journal_index_helpers import (
    APP,
    Clock,
    FakeJournal,
    Spy,
    make,
    progress,
    settle,
    storage,
    verstrs,
)
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.journal_follow import WorkspaceJournal

DAY_SEC = 86_400


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal():
    return FakeJournal()


def _workspace(journal, clock):
    return WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)


def _first_life(tmp_path, monkeypatch, journal, clock):
    """An index that listed the store, followed the journal and persisted
    its mark; the store it reads."""
    st = storage(tmp_path)
    for i in range(3):
        make(st, i)
    Spy(st, monkeypatch)
    ws = _workspace(journal, clock)
    index = ExperimentIndex(st, APP, str(tmp_path / "i.sqlite"), full_sweep_sec=3600)
    ws.watch(index)
    settle(index)
    ws.tick()
    settle(index)
    return st


def _restarted(st, tmp_path, monkeypatch):
    spy = Spy(st, monkeypatch)
    return ExperimentIndex(st, APP, str(tmp_path / "i.sqlite"), full_sweep_sec=3600), spy


def test_a_restart_with_a_fresh_mark_replays_the_journal_without_listing(
        tmp_path, monkeypatch, journal, clock):
    st = _first_life(tmp_path, monkeypatch, journal, clock)
    clock.t += 100
    missed = make(st, 10)  # while the server was down
    journal.put(clock.t * 1000, missed)
    clock.t += 500
    new = make(st, 11)
    journal.put(clock.t * 1000, new)

    index, spy = _restarted(st, tmp_path, monkeypatch)
    ws = _workspace(journal, clock)  # its own cursor starts now: only the mark reaches back
    ws.watch(index)
    assert progress(index)[0] == "journal"
    ws.tick()
    settle(index)

    assert {missed, new} <= verstrs(index)
    assert len(verstrs(index)) == 5
    assert None not in spy.files and spy.names == 0


def test_a_mark_past_the_journal_retention_lists_fully_behind_serving(
        tmp_path, monkeypatch, journal, clock):
    st = _first_life(tmp_path, monkeypatch, journal, clock)
    clock.t += 3 * DAY_SEC  # the journal kept two days
    missed = make(st, 10)

    index, spy = _restarted(st, tmp_path, monkeypatch)
    spy.block_names = True  # the full listing hangs on the store
    ws = _workspace(journal, clock)
    ws.watch(index)
    index.refresh()
    assert progress(index) == ("full_listing", None)
    assert len(verstrs(index)) == 3  # the persisted rows serve meanwhile

    new = make(st, 11)
    journal.put(clock.t * 1000, new)
    ws.tick()
    index.refresh()  # does not wait for the listing
    assert new in verstrs(index) and missed not in verstrs(index)
    assert not index.refreshing

    spy.release.set()
    settle(index)
    assert missed in verstrs(index)
    assert progress(index) == ("idle", None)


def test_a_full_listing_run_since_the_mark_lets_the_next_restart_replay(
        tmp_path, monkeypatch, journal, clock):
    st = _first_life(tmp_path, monkeypatch, journal, clock)
    clock.t += 3 * DAY_SEC
    index, _ = _restarted(st, tmp_path, monkeypatch)
    ws = _workspace(journal, clock)
    ws.watch(index)
    settle(index)
    ws.tick()
    settle(index)

    clock.t += 60
    new = make(st, 12)
    journal.put(clock.t * 1000, new)
    again, spy = _restarted(st, tmp_path, monkeypatch)
    ws = _workspace(journal, clock)
    ws.watch(again)
    ws.tick()
    settle(again)
    assert new in verstrs(again)
    assert None not in spy.files and spy.names == 0


def test_an_index_never_marked_reports_idle_before_its_first_refresh(tmp_path):
    index = ExperimentIndex(storage(tmp_path), APP)
    assert progress(index) == ("idle", None)
