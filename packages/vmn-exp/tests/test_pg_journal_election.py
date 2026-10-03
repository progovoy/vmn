"""Plan 11 §4.3: one journal reader per workspace across replicas (the
advisory-lock leader), relaying hints as ``NOTIFY vmn_hint``; followers wake
on ``LISTEN vmn_gen``."""
import time

import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.snapshot import LocalSnapshotStorage  # noqa: E402
from vmn_exp.storage.journal import journaled  # noqa: E402
from vmn_exp.storage.journal_sinks import journal_list_fn  # noqa: E402
from vmn_exp.ui.cache_pg import PostgresStore  # noqa: E402
from vmn_exp.ui.elected_index import ElectedIndex  # noqa: E402
from vmn_exp.ui.journal_follow import WorkspaceJournal  # noqa: E402
from vmn_exp.ui.pg_election import AdvisoryElection  # noqa: E402
from vmn_exp.ui.pg_listen import PgListener  # noqa: E402
from vmn_exp.ui.refresher import Refresher  # noqa: E402


class FakeIndex:
    def __init__(self, app_name):
        self.app_name = app_name
        self.hints, self.reconciles, self.journaled = [], 0, False

    def hint(self, name):
        self.hints.append(name)

    def reconcile(self):
        self.reconciles += 1


def _until(check, timeout=5):
    deadline = time.time() + timeout
    while not check():
        assert time.time() < deadline, "timed out"
        time.sleep(0.02)


@pytest.fixture
def store(tmp_path):
    return journaled(LocalSnapshotStorage(str(tmp_path), "runs"), writer_id="w1")


def _write(store, app, verstr):
    store.save(app, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})


class JournalReplica:
    def __init__(self, store, dsn):
        self.listed = 0
        real = journal_list_fn(store)

        def list_fn(prefix, start_after=None):
            self.listed += 1
            return real(prefix, start_after)

        self.election = AdvisoryElection(dsn)
        self.journal = WorkspaceJournal(
            list_fn, PostgresStore(dsn), "ws", election=self.election,
            relay=lambda payload: self.election.notify("vmn_hint", payload),
            skew_window_sec=0,  # no re-read overlap: a handover must resume the cursor
        )
        self.index = FakeIndex("app")
        self.journal.watch(self.index)
        self.listener = PgListener(dsn, {"vmn_hint": self.journal.receive})

    def close(self):
        self.listener.stop()
        self.election.close()


def _tick_both(a, b):
    a.journal.tick()
    b.journal.tick()


@pytest.fixture
def journals(store, pg_dsn):
    made = [JournalReplica(store, pg_dsn), JournalReplica(store, pg_dsn)]
    yield made
    for replica in made:
        replica.close()


def test_one_replica_reads_the_journal_and_both_get_hints(store, journals):
    a, b = journals
    _until(lambda: a.listener.listening and b.listener.listening)
    _tick_both(a, b)  # start the cursor before the first write
    _write(store, "app", "1.0.0-dev.a")
    for _ in range(3):
        a.journal.tick()
        b.journal.tick()
    assert sorted([a.listed > 0, b.listed > 0]) == [False, True]
    _until(lambda: "1.0.0-dev.a" in a.index.hints and "1.0.0-dev.a" in b.index.hints)


def test_journal_reader_hands_over_with_the_cursor(store, journals):
    a, b = journals
    _until(lambda: a.listener.listening and b.listener.listening)
    _tick_both(a, b)  # start the cursor before the first write
    _write(store, "app", "1.0.0-dev.a")
    a.journal.tick()
    b.journal.tick()
    leader, other = (a, b) if a.listed else (b, a)
    _until(lambda: "1.0.0-dev.a" in other.index.hints)
    leader.election.close()
    other.index.hints.clear()
    _write(store, "app", "1.0.0-dev.b")
    other.journal.tick()
    assert other.listed > 0
    assert "1.0.0-dev.a" not in other.index.hints
    assert "1.0.0-dev.b" in other.index.hints


def test_follower_wakes_on_vmn_gen_before_its_poll(tmp_path, pg_dsn):
    st = LocalSnapshotStorage(str(tmp_path / "s"), area="runs")
    st.save("app", "0.0.1-dev.x", {"verstr": "0.0.1-dev.x", "timestamp": "2026"}, {})
    lead_el, follow_el = AdvisoryElection(pg_dsn), AdvisoryElection(pg_dsn)
    leader = ElectedIndex(st, "app", PostgresStore(pg_dsn), lead_el)
    leader.refresh()
    assert leader.leading
    follower = ElectedIndex(st, "app", PostgresStore(pg_dsn), follow_el)
    refresher = Refresher(interval_sec=30)
    listener = PgListener(pg_dsn, {"vmn_gen": refresher.wake_scope})
    try:
        _until(lambda: listener.listening)
        refresher.snapshot(follower)
        _until(lambda: len(follower.snapshot().rows) == 1)
        st.save("app", "0.0.1-dev.y", {"verstr": "0.0.1-dev.y", "timestamp": "2027"}, {})
        leader.refresh()
        _until(lambda: len(follower.snapshot().rows) == 2, timeout=3)
    finally:
        listener.stop()
        refresher.stop()
        lead_el.close()
        follow_el.close()
