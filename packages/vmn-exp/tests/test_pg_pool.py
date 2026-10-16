"""One pool per DSN (plan 25 F4): timeouts, keepalives, migrations once,
concurrent requests, and the cache surviving a killed backend."""
import threading
import time

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

from pg_locks import table_locked, terminate, wait_for_waiters  # noqa: E402

from vmn_exp.ui import migrations, pg_pool  # noqa: E402
from vmn_exp.ui.cache_pg import PostgresStore  # noqa: E402
from vmn_exp.ui.control_plane_pg import PostgresControlPlane  # noqa: E402
from vmn_exp.ui.search_pg import PgRowSearch  # noqa: E402

_SHORT_STATEMENTS = "?options=-c%20statement_timeout%3D300"


def in_thread(fn):
    out = {}

    def run():
        start = time.monotonic()
        try:
            out["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - the test inspects it
            out["error"] = exc
        out["elapsed"] = time.monotonic() - start

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def _counting_migrations(monkeypatch, fail_first=False):
    calls = []
    real = migrations.apply_migrations

    def counting(conn):
        calls.append(1)
        if fail_first and len(calls) == 1:
            raise psycopg.OperationalError("down")
        return real(conn)

    monkeypatch.setattr(migrations, "apply_migrations", counting)
    return calls


def test_one_pool_per_dsn(pg_dsn):
    assert pg_pool.pool(pg_dsn) is pg_pool.pool(pg_dsn)


def test_pooled_connections_carry_timeouts_and_keepalives(pg_dsn):
    with pg_pool.pool(pg_dsn).connection() as conn:
        (statement,) = conn.execute("SHOW statement_timeout").fetchone()
        (idle_tx,) = conn.execute("SHOW idle_in_transaction_session_timeout").fetchone()
        params = conn.info.get_parameters()
    assert statement == "30s"
    assert idle_tx == "1min"
    assert params["connect_timeout"] == "5"
    assert params["keepalives"] == "1"
    assert "keepalives_idle" in params


def test_dsn_settings_beat_the_defaults(pg_dsn):
    dsn = pg_dsn + _SHORT_STATEMENTS + "&connect_timeout=2"
    with pg_pool.pool(dsn).connection() as conn:
        (statement,) = conn.execute("SHOW statement_timeout").fetchone()
        params = conn.info.get_parameters()
    assert statement == "300ms"
    assert params["connect_timeout"] == "2"


def test_dedicated_connections_carry_the_same_settings(pg_dsn):
    with pg_pool.connect(pg_dsn) as conn:
        assert conn.autocommit
        (statement,) = conn.execute("SHOW statement_timeout").fetchone()
        params = conn.info.get_parameters()
    assert statement == "30s"
    assert params["keepalives"] == "1"


def test_migrations_run_once_across_three_replicas_starting_together(pg_dsn, monkeypatch):
    calls = _counting_migrations(monkeypatch)
    replicas = [
        lambda: PostgresStore(pg_dsn).generation("app"),
        lambda: PostgresControlPlane(pg_dsn).list("workspace"),
        lambda: PgRowSearch(pg_dsn).search(["ws"], "", 10),
    ]
    threads = [in_thread(fn) for fn in replicas]
    for thread, out in threads:
        thread.join(20)
        assert "error" not in out, out
    store = PostgresStore(pg_dsn)
    store.save("app", {"a": {"verstr": "1"}}, set())
    with pg_pool.pool(pg_dsn).connection() as conn:
        pid = conn.info.backend_pid
    terminate(pg_dsn, pid)
    assert set(store.load("app")) == {"a"}
    assert len(calls) == 1
    with psycopg.connect(pg_dsn) as conn:
        (n,) = conn.execute("SELECT count(*) FROM vmn_schema_migrations").fetchone()
    assert n == len(migrations.migration_files())


def test_failed_migrations_are_retried_on_the_next_call(pg_dsn, monkeypatch):
    calls = _counting_migrations(monkeypatch, fail_first=True)
    store = PostgresStore(pg_dsn)
    assert store.generation("app") == 0
    store.save("app", {"a": {"verstr": "1"}}, set())
    assert set(store.load("app")) == {"a"}
    assert len(calls) == 2


def test_cache_request_killed_mid_flight_fails_and_the_next_succeeds(pg_dsn):
    store = PostgresStore(pg_dsn)
    store.save("app", {"a": {"verstr": "1"}}, set())
    with table_locked(pg_dsn, "vmn_records"):
        thread, out = in_thread(lambda: store.load("app"))
        terminate(pg_dsn, *wait_for_waiters(pg_dsn, 1))
        thread.join(5)
    assert out["value"] == {}
    assert out["elapsed"] < 5
    assert set(store.load("app")) == {"a"}


def test_cache_request_past_the_statement_timeout_fails_fast(pg_dsn):
    PostgresStore(pg_dsn).save("app", {"a": {"verstr": "1"}}, set())
    store = PostgresStore(pg_dsn + _SHORT_STATEMENTS)
    store.generation("app")  # connected and checked before the lock
    with table_locked(pg_dsn, "vmn_records"):
        start = time.monotonic()
        assert store.load("app") == {}
        assert time.monotonic() - start < 3
    assert set(store.load("app")) == {"a"}


def test_concurrent_cache_requests_run_concurrently(pg_dsn):
    store = PostgresStore(pg_dsn)
    store.save("app", {"a": {"verstr": "1"}}, set())
    with table_locked(pg_dsn, "vmn_records"):
        threads = [in_thread(lambda: store.load("app")) for _ in range(2)]
        wait_for_waiters(pg_dsn, 2)
    for thread, out in threads:
        thread.join(5)
        assert set(out["value"]) == {"a"}


def test_concurrent_sleeps_overlap(pg_dsn):
    pool = pg_pool.pool(pg_dsn)

    def sleep():
        with pool.connection() as conn:
            conn.execute("SELECT pg_sleep(0.5)")

    start = time.monotonic()
    threads = [in_thread(sleep) for _ in range(2)]
    for thread, out in threads:
        thread.join(5)
        assert "error" not in out, out
    assert time.monotonic() - start < 0.9
