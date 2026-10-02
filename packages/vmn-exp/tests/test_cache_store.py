"""CacheStore protocol: load/save, generations, load_since deltas, kv cache."""
import pytest

from vmn_exp.core import index_store
from vmn_exp.core.index_store import CacheStore, IndexStore, SqliteStore

APP = "app"


@pytest.fixture(params=["sqlite"])
def cache_store(request, tmp_path):
    factories = {"sqlite": lambda: SqliteStore(str(tmp_path / "idx.sqlite"))}
    return factories[request.param]()


def _rec(verstr, **extra):
    return dict({"verstr": verstr}, **extra)


def test_index_store_is_sqlite_store_alias():
    assert IndexStore is SqliteStore
    assert isinstance(SqliteStore(None), CacheStore)


def test_save_then_load_round_trips(cache_store):
    cache_store.save(
        APP, {"a": _rec("0.0.1")}, set(), {"a": {"rs_sig": "s", "run_state": {"x": 1}}}
    )
    loaded = cache_store.load(APP)
    assert loaded["a"]["verstr"] == "0.0.1"
    assert loaded["a"]["rs_sig"] == "s"
    assert loaded["a"]["run_state"] == {"x": 1}


def test_removed_keys_disappear(cache_store):
    cache_store.save(APP, {"a": _rec("1"), "b": _rec("2")}, set())
    cache_store.save(APP, {}, {"a"})
    assert set(cache_store.load(APP)) == {"b"}


def test_generation_starts_at_zero_and_bumps_per_save(cache_store):
    assert cache_store.generation(APP) == 0
    cache_store.save(APP, {"a": _rec("1")}, set())
    g1 = cache_store.generation(APP)
    cache_store.save(APP, {}, set(), {"a": {"rs_sig": "x"}})
    g2 = cache_store.generation(APP)
    assert 0 < g1 < g2
    assert cache_store.generation("other") == 0


def test_noop_save_does_not_bump_generation(cache_store):
    cache_store.save(APP, {"a": _rec("1")}, set())
    gen = cache_store.generation(APP)
    cache_store.save(APP, {}, set(), {})
    assert cache_store.generation(APP) == gen


def test_load_since_returns_only_changes(cache_store):
    cache_store.save(APP, {"a": _rec("1"), "b": _rec("2")}, set())
    gen = cache_store.generation(APP)
    cache_store.save(APP, {"c": _rec("3")}, set(), {"b": {"rs_sig": "s2"}})
    changed, removed, new_gen = cache_store.load_since(APP, gen)
    assert set(changed) == {"b", "c"}
    assert changed["b"]["verstr"] == "2" and changed["b"]["rs_sig"] == "s2"
    assert removed == set()
    assert new_gen == cache_store.generation(APP) > gen


def test_load_since_current_generation_is_empty(cache_store):
    cache_store.save(APP, {"a": _rec("1")}, set())
    gen = cache_store.generation(APP)
    assert cache_store.load_since(APP, gen) == ({}, set(), gen)


def test_load_since_reports_removals(cache_store):
    cache_store.save(APP, {"a": _rec("1"), "b": _rec("2")}, set())
    gen = cache_store.generation(APP)
    cache_store.save(APP, {}, {"a"})
    changed, removed, _ = cache_store.load_since(APP, gen)
    assert changed == {} and removed == {"a"}


def test_readded_key_is_changed_not_removed(cache_store):
    cache_store.save(APP, {"a": _rec("1")}, set())
    gen = cache_store.generation(APP)
    cache_store.save(APP, {}, {"a"})
    cache_store.save(APP, {"a": _rec("2")}, set())
    changed, removed, _ = cache_store.load_since(APP, gen)
    assert changed["a"]["verstr"] == "2" and removed == set()


def test_tombstones_trimmed_and_stale_follower_gets_full_load(cache_store, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(index_store, "_now", lambda: now[0])
    cache_store.save(APP, {"a": _rec("1"), "b": _rec("2")}, set())
    old_gen = cache_store.generation(APP)
    cache_store.save(APP, {}, {"a"})
    now[0] += index_store.TOMBSTONE_TTL_SEC + 1
    cache_store.save(APP, {"c": _rec("3")}, set())  # trims the old tombstone
    recent_gen = cache_store.generation(APP)
    changed, removed, new_gen = cache_store.load_since(APP, old_gen)
    assert removed is index_store.FULL_LOAD
    assert set(changed) == {"b", "c"}
    assert new_gen == recent_gen
    cache_store.save(APP, {"d": _rec("4")}, set())
    changed, removed, _ = cache_store.load_since(APP, recent_gen)
    assert set(changed) == {"d"} and removed == set()


def test_kv_round_trip_and_fingerprint_mismatch(cache_store):
    assert cache_store.kv_get("ver:app", "fp1") is None
    cache_store.kv_put("ver:app", "fp1", [{"v": 1}])
    assert cache_store.kv_get("ver:app", "fp1") == [{"v": 1}]
    assert cache_store.kv_get("ver:app", "fp2") is None
    cache_store.kv_put("ver:app", "fp2", {"x": 2})
    assert cache_store.kv_get("ver:app", "fp2") == {"x": 2}


def test_disabled_store_never_raises():
    store = SqliteStore(None)
    store.save(APP, {"a": _rec("1")}, set())
    assert store.load(APP) == {}
    assert store.generation(APP) == 0
    assert store.load_since(APP, 0) == ({}, set(), 0)
    store.kv_put("s", "f", 1)
    assert store.kv_get("s", "f") is None


def test_kv_get_never_raises_on_undecodable_payload(cache_store):
    cache_store._conn.execute(
        "INSERT INTO exp_index_kv (scope, fingerprint, payload) VALUES ('s', 'f', '{bad')"
    )
    assert cache_store.kv_get("s", "f") is None
