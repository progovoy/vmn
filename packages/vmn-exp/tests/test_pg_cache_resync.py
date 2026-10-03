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


def test_a_truncated_cache_is_rebuilt_under_a_shadow_generation(store, tmp_path):
    from vmn_exp.core.index import ExperimentIndex
    from vmn_exp.snapshot import LocalSnapshotStorage
    from vmn_exp.ui.cache_rebuild import PgShadow
    from vmn_exp.ui.cache_resync import WorkspaceCache

    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    for i in range(3):
        st.save("app", f"0.0.1-dev.abc.r{i}", {"timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
    index = ExperimentIndex(st, "app", cache_store=store).refresh()
    index.refresh()
    health = PgHealth(store)
    health.observe("app")
    seen = store.generation("app")
    cache = WorkspaceCache("ws", health=health, check_sec=0,
                           target_of=lambda: PgShadow(store, health, lambda app: app))
    cache.note("app", st, lambda: index)
    _sql(store, "TRUNCATE vmn_records, vmn_run_states, vmn_tombstones, vmn_scope_gen")
    assert cache.tick() == "truncated"
    assert cache.wait(20)
    assert len(store.load("app")) == 3
    assert store.generation("app") > seen
    assert health.problem() is None
