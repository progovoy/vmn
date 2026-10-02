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
