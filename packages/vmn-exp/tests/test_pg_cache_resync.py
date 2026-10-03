"""Plan 11 §4.6 on Postgres: a truncated cache (generation regression or a
missing ``vmn_cache_meta`` row) or another schema is detected, and a rebuild
replaces a scope's rows in one transaction under a generation past any a
follower saw."""
import pytest

from vmn_exp.ui.cache_health import PgHealth

pytest.importorskip("psycopg")


@pytest.fixture
def store(pg_dsn):
    from vmn_exp.ui.cache_pg import PostgresStore

    return PostgresStore(pg_dsn)


def _rec(n):
    return {"meta": {"n": n}, "rs_sig": None, "run_state": {}}


def _sql(store, statement):
    import psycopg

    with psycopg.connect(store._dsn, autocommit=True) as conn:
        conn.execute(statement)


def test_a_healthy_cache(store):
    store.save("app", {"a": _rec(1)}, ())
    health = PgHealth(store)
    health.observe("app")
    assert health.problem() is None


def test_a_generation_regression_is_truncation(store):
    store.save("app", {"a": _rec(1)}, ())
    store.save("app", {"a": _rec(2)}, ())
    health = PgHealth(store)
    health.observe("app")
    _sql(store, "TRUNCATE vmn_records, vmn_run_states, vmn_tombstones, vmn_scope_gen")
    assert health.problem() == "truncated"


def test_a_missing_meta_row_is_truncation(store):
    store.save("app", {"a": _rec(1)}, ())
    health = PgHealth(store)
    _sql(store, "DELETE FROM vmn_cache_meta")
    assert health.problem() == "truncated"


def test_another_schema_version(store):
    store.save("app", {"a": _rec(1)}, ())
    health = PgHealth(store)
    _sql(store, "UPDATE vmn_cache_meta SET v = 'exp-index-0'")
    assert health.problem() == "schema"


def test_replace_scope_swaps_rows_atomically_past_the_floor(store):
    store.save("app", {"a": _rec(1), "b": _rec(1)}, ())
    store.replace_scope("app", {"a": _rec(2), "c": _rec(3)}, floor=40)
    assert store.generation("app") == 41
    assert set(store.load("app")) == {"a", "c"}
    changed, removed, gen = store.load_since("app", 40)
    assert set(changed) == {"a", "c"} and "b" in removed and gen == 41
