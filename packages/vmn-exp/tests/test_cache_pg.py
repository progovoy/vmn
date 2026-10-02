"""Postgres-only behaviour of PostgresStore: NOTIFY, schema reset, migrations."""
import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.ui import cache_pg  # noqa: E402
from vmn_exp.ui.cache_pg import PostgresStore  # noqa: E402
from vmn_exp.ui.migrations import apply_migrations  # noqa: E402


def test_save_notifies_scope_after_commit(pg_dsn):
    store = PostgresStore(pg_dsn)
    with psycopg.connect(pg_dsn, autocommit=True) as listener:
        listener.execute("LISTEN vmn_gen")
        store.save("app", {"a": {"verstr": "1"}}, set())
        notes = list(listener.notifies(timeout=5, stop_after=1))
    assert [n.payload for n in notes] == ["0:app"]


def test_schema_mismatch_truncates_cache_but_not_control_plane(pg_dsn):
    from vmn_exp.ui.cache_pg import PostgresControlPlane

    store = PostgresStore(pg_dsn)
    store.save("app", {"a": {"verstr": "1"}}, set())
    PostgresControlPlane(pg_dsn).put("token", "t1", {"id": "t1"})
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("UPDATE vmn_cache_meta SET v = 'old' WHERE k = 'schema_version'")
    again = PostgresStore(pg_dsn)
    assert again.load("app") == {}
    assert again.generation("app") == 0
    assert PostgresControlPlane(pg_dsn).get("token", "t1") == {"id": "t1"}


def test_migrations_are_idempotent(pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        apply_migrations(conn)
        apply_migrations(conn)
        (n,) = conn.execute("SELECT count(*) FROM vmn_schema_migrations").fetchone()
    assert n == 2


def test_unreachable_database_never_raises():
    store = PostgresStore("postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=1")
    store.save("app", {"a": {"verstr": "1"}}, set())
    assert store.load("app") == {}
    assert store.generation("app") == 0
    assert store.load_since("app", 0) == ({}, set(), 0)
    store.kv_put("s", "f", 1)
    assert store.kv_get("s", "f") is None


def test_scope_may_be_workspace_and_app(pg_dsn):
    store = PostgresStore(pg_dsn)
    store.save((1, "app"), {"a": {"verstr": "1"}}, set())
    assert set(store.load((1, "app"))) == {"a"}
    assert store.load("app") == {}
    assert cache_pg.scope_key((1, "app")) == (0, 1, "app")
