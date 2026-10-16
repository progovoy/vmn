"""ControlPlaneStore contract, on SQLite and Postgres."""
import pytest

from vmn_exp.ui.control_plane import SQLiteControlPlane


@pytest.fixture(params=["sqlite", "postgres"])
def cp(request, tmp_path):
    if request.param == "sqlite":
        return SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    from vmn_exp.ui.cache_pg import PostgresControlPlane

    return PostgresControlPlane(request.getfixturevalue("pg_dsn"))


def test_put_get_and_overwrite(cp):
    assert cp.get("token", "a") is None
    cp.put("token", "a", {"v": 1})
    cp.put("token", "a", {"v": 2})
    assert cp.get("token", "a") == {"v": 2}


def test_expiry_applies_to_sessions_and_logins(cp):
    for kind in ("session", "login"):
        cp.put(kind, "k", {"x": kind}, expires_at=100)
        assert cp.get(kind, "k", now=50) == {"x": kind}
        assert cp.get(kind, "k", now=150) is None
        assert cp.get(kind, "k") == {"x": kind}


def test_pop_is_single_use(cp):
    cp.put("login", "s", {"n": 1}, expires_at=100)
    assert cp.pop("login", "s", now=10) == {"n": 1}
    assert cp.pop("login", "s", now=10) is None


def test_delete_reports_whether_it_existed(cp):
    cp.put("token", "a", {})
    assert cp.delete("token", "a") is True
    assert cp.delete("token", "a") is False


def test_list_in_insertion_order(cp):
    for key in ("b", "a", "c"):
        cp.put("token", key, {"id": key})
    assert [d["id"] for d in cp.list("token")] == ["b", "a", "c"]


def test_sweep_expired_drops_expired_sessions_and_logins_only(cp):
    for kind in ("session", "login"):
        cp.put(kind, "old", {"k": kind}, expires_at=100)
        cp.put(kind, "new", {"k": kind}, expires_at=300)
    cp.put("token", "t", {"k": "token"})
    cp.sweep_expired(now=200)
    for kind in ("session", "login"):
        assert cp.get(kind, "old") is None
        assert cp.get(kind, "new") == {"k": kind}
    assert cp.get("token", "t") == {"k": "token"}


def test_page_is_newest_first_and_count_is_total(cp):
    for i in range(5):
        cp.put("audit", f"{i:03d}", {"i": i})
    assert [d["i"] for d in cp.page("audit", offset=1, limit=2)] == [3, 2]
    assert cp.page("audit", offset=5, limit=2) == []
    assert cp.count("audit") == 5


def test_scan_yields_every_doc_oldest_first_in_batches(cp):
    for i in range(5):
        cp.put("audit", f"{i:03d}", {"i": i})
    scan = cp.scan("audit", batch=2)
    assert next(scan) == {"i": 0}
    assert [d["i"] for d in scan] == [1, 2, 3, 4]


def test_delete_keys_below_drops_lower_keys(cp):
    for key in ("001-a", "002-b", "003-c"):
        cp.put("audit", key, {"k": key})
    cp.delete_keys_below("audit", "002")
    assert [d["k"] for d in cp.scan("audit")] == ["002-b", "003-c"]


def test_server_key_is_generated_once_and_kept(cp):
    key = cp.server_key("token_hmac")
    assert isinstance(key, bytes) and len(key) == 32
    assert cp.server_key("token_hmac") == key
    assert cp.server_key("other") != key


def test_server_key_survives_a_new_store_instance(tmp_path):
    path = str(tmp_path / "cp.sqlite3")
    assert SQLiteControlPlane(path).server_key("k") == SQLiteControlPlane(path).server_key("k")
