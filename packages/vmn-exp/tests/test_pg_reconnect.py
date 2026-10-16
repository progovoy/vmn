"""Control plane, search, election and LISTEN survive a killed backend
(plan 25 F4); pooled stores serve concurrent requests concurrently."""
import threading

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

from pg_locks import table_locked, terminate, until, wait_for_waiters  # noqa: E402
from test_pg_pool import in_thread  # noqa: E402

from vmn_exp.ui.control_plane_pg import PostgresControlPlane  # noqa: E402
from vmn_exp.ui.pg_election import AdvisoryElection  # noqa: E402
from vmn_exp.ui.pg_listen import PgListener  # noqa: E402
from vmn_exp.ui.refresher import Refresher  # noqa: E402
from vmn_exp.ui.search_pg import PgRowSearch  # noqa: E402

_ROW = {"verstr": "0.0.1-dev.a", "status": "succeeded"}


@pytest.fixture
def control_plane(pg_dsn):
    cp = PostgresControlPlane(pg_dsn)
    cp.put("workspace", "w", {"name": "w"})
    return cp


@pytest.fixture
def search(pg_dsn):
    rows = PgRowSearch(pg_dsn)
    rows.sync("ws", "app", 1, lambda: [_ROW])
    return rows


def _search_hits(search):
    return [row for (_, _, row) in search.search(["ws"], "", 10)]


def test_control_plane_request_killed_mid_flight_raises_and_the_next_succeeds(
        pg_dsn, control_plane):
    with table_locked(pg_dsn, "vmn_workspaces"):
        thread, out = in_thread(lambda: control_plane.list("workspace"))
        terminate(pg_dsn, *wait_for_waiters(pg_dsn, 1))
        thread.join(5)
    assert isinstance(out["error"], psycopg.OperationalError)
    assert out["elapsed"] < 5
    assert control_plane.list("workspace") == [{"name": "w"}]


def test_control_plane_requests_run_concurrently(pg_dsn, control_plane):
    with table_locked(pg_dsn, "vmn_workspaces"):
        threads = [in_thread(lambda: control_plane.get("workspace", "w")) for _ in range(2)]
        wait_for_waiters(pg_dsn, 2)
    for thread, out in threads:
        thread.join(5)
        assert out["value"] == {"name": "w"}


def test_search_request_killed_mid_flight_raises_and_the_next_succeeds(pg_dsn, search):
    with table_locked(pg_dsn, "vmn_search_rows"):
        thread, out = in_thread(lambda: _search_hits(search))
        terminate(pg_dsn, *wait_for_waiters(pg_dsn, 1))
        thread.join(5)
    assert isinstance(out["error"], psycopg.OperationalError)
    assert out["elapsed"] < 5
    assert _search_hits(search) == [_ROW]


def test_search_requests_run_concurrently(pg_dsn, search):
    with table_locked(pg_dsn, "vmn_search_rows"):
        threads = [in_thread(lambda: _search_hits(search)) for _ in range(2)]
        wait_for_waiters(pg_dsn, 2)
    for thread, out in threads:
        thread.join(5)
        assert out["value"] == [_ROW]


def test_election_sits_out_once_then_leads_again_after_its_backend_dies(pg_dsn):
    election = AdvisoryElection(pg_dsn)
    try:
        assert election.lead("s")
        terminate(pg_dsn, election.backend_pid)
        assert not election.lead("s")
        assert election.lead("s")
        with psycopg.connect(pg_dsn, autocommit=True) as conn:
            conn.execute("LISTEN ch")
            election.notify("ch", "after")
            notes = list(conn.notifies(timeout=5, stop_after=1))
        assert [n.payload for n in notes] == ["after"]
    finally:
        election.close()


def test_election_connection_carries_keepalives(pg_dsn):
    election = AdvisoryElection(pg_dsn)
    try:
        election.lead("s")
        assert election._conn.info.get_parameters()["keepalives"] == "1"
    finally:
        election.close()


def test_listener_relistens_and_asks_for_a_resync_after_its_backend_dies(pg_dsn):
    got, resyncs = [], []
    listener = PgListener(pg_dsn, {"ch": got.append}, on_resync=lambda: resyncs.append(1))
    try:
        until(lambda: listener.listening)
        assert resyncs == []
        terminate(pg_dsn, listener.backend_pid)
        until(lambda: resyncs and listener.listening)
        with psycopg.connect(pg_dsn, autocommit=True) as conn:
            conn.execute("SELECT pg_notify('ch', 'after')")
        until(lambda: got == ["after"])
    finally:
        listener.stop()


class _CountingIndex:
    def __init__(self):
        self.refreshed = threading.Event()
        self.count = 0

    def refresh(self):
        self.count += 1
        if self.count > 1:
            self.refreshed.set()

    def snapshot(self):
        return None


def test_refresher_wake_all_refreshes_every_watch_at_once():
    refresher = Refresher(interval_sec=60)
    indexes = [_CountingIndex(), _CountingIndex()]
    try:
        for index in indexes:
            refresher.snapshot(index)
        until(lambda: all(i.count == 1 for i in indexes))
        refresher.wake_all()
        for index in indexes:
            assert index.refreshed.wait(5)
    finally:
        refresher.stop()
