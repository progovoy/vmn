"""Plan 11 §4.3: in Postgres mode one replica per scope refreshes from the
store (the leader); the others only apply the cache's deltas."""
import time

import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.snapshot import LocalSnapshotStorage  # noqa: E402
from vmn_exp.ui.cache_pg import PostgresStore  # noqa: E402
from vmn_exp.ui.elected_index import ElectedIndex  # noqa: E402
from vmn_exp.ui.pg_election import AdvisoryElection  # noqa: E402
from vmn_exp.ui.refresher import Refresher  # noqa: E402

APP = "app"
TICK = 0.1


class CountingStorage:
    def __init__(self, storage):
        self._storage, self.listings = storage, 0

    def __getattr__(self, name):
        if name.startswith("list"):
            self.listings += 1
        return getattr(self._storage, name)


def _verstr(i):
    return f"0.0.1-dev.abc.r{i}"


def _make(st, i):
    st.save(APP, _verstr(i), {"verstr": _verstr(i), "timestamp": f"2026-01-01T00:0{i}:00Z"}, {})


class Replica:
    def __init__(self, st, dsn):
        self.storage = CountingStorage(st)
        self.election = AdvisoryElection(dsn)
        self.index = ElectedIndex(self.storage, APP, PostgresStore(dsn), self.election)
        self.refresher = Refresher(interval_sec=TICK)

    def rows(self):
        return [r["verstr"] for r in self.refresher.snapshot(self.index).rows]

    def stop(self):
        self.refresher.stop()
        self.election.close()


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


@pytest.fixture
def replicas(st, pg_dsn):
    made = [Replica(st, pg_dsn), Replica(st, pg_dsn)]
    yield made
    for replica in made:
        replica.stop()


def _until(check, timeout=10):
    deadline = time.time() + timeout
    while not check():
        assert time.time() < deadline, "timed out"
        time.sleep(0.02)


def test_exactly_one_replica_lists(st, replicas):
    _make(st, 0)
    a, b = replicas
    _until(lambda: a.rows() == [_verstr(0)] and b.rows() == [_verstr(0)])
    time.sleep(5 * TICK)
    assert sorted([a.index.leading, b.index.leading]) == [False, True]
    follower = b if a.index.leading else a
    assert follower.storage.listings == 0


def test_follower_snapshot_equals_leader(st, replicas):
    a, b = replicas
    for i in range(3):
        _make(st, i)
    want = sorted(_verstr(i) for i in range(3))
    _until(lambda: sorted(a.rows()) == want and sorted(b.rows()) == want)
    leader, follower = (a, b) if a.index.leading else (b, a)
    assert follower.index.snapshot().rows == leader.index.snapshot().rows


def test_killing_leader_connection_hands_over(st, replicas, pg_dsn):
    _make(st, 0)
    a, b = replicas
    _until(lambda: a.rows() and b.rows())
    leader, follower = (a, b) if a.index.leading else (b, a)
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(%s)", (leader.election.backend_pid,))
    _until(lambda: follower.rows() and follower.index.leading, timeout=4 * TICK + 2)
    _make(st, 1)
    want = sorted([_verstr(0), _verstr(1)])
    _until(lambda: sorted(follower.rows()) == want and sorted(leader.rows()) == want)


def test_election_lock_is_exclusive_until_released(pg_dsn):
    one, two = AdvisoryElection(pg_dsn), AdvisoryElection(pg_dsn)
    try:
        assert one.lead("s") and one.lead("s")
        assert not two.lead("s")
        assert two.lead("other")
        one.close()
        assert two.lead("s")
    finally:
        one.close()
        two.close()
