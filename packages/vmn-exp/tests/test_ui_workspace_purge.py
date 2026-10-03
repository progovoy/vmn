"""Disconnecting a workspace purges its cache rows after 7 days (plan 11 §6.3)."""
import pytest

from vmn_exp.ui.purge import PURGE_AFTER_SEC, purge_disconnected
from vmn_exp.ui.workspaces import WorkspaceManager

DAY = 86400.0


class _Cache:
    def __init__(self):
        self.purged = []

    def purge_workspace(self, workspace_id):
        self.purged.append(workspace_id)


def _manager(tmp_path):
    manager = WorkspaceManager(str(tmp_path))
    manager.add_store("a", f"file://{tmp_path}/a")
    manager.add_store("b", f"file://{tmp_path}/b")
    return manager


def test_disconnect_marks_the_workspace_and_persists(tmp_path):
    manager = _manager(tmp_path)
    manager.disconnect("a", now=100.0)
    assert WorkspaceManager(str(tmp_path)).get("a").disconnected_at == 100.0


def test_purge_waits_seven_days(tmp_path):
    assert PURGE_AFTER_SEC == 7 * DAY
    manager, cache = _manager(tmp_path), _Cache()
    manager.disconnect("a", now=0.0)
    ids = {"a": 11, "b": 12}
    assert purge_disconnected(manager, cache, lambda ws: ids[ws.name], now=6 * DAY) == []
    assert cache.purged == [] and manager.get("a") is not None
    assert purge_disconnected(manager, cache, lambda ws: ids[ws.name], now=7 * DAY + 1) == ["a"]
    assert cache.purged == [11]
    assert manager.get("a") is None and manager.get("b") is not None


def test_postgres_purge_drops_only_that_workspace_rows(pg_dsn):
    pytest.importorskip("psycopg")
    from vmn_exp.ui.cache_pg import PostgresStore

    store = PostgresStore(pg_dsn)
    store.save((1, "app"), {"a": {"verstr": "1"}}, set())
    store.kv_put((1, "app"), "f", {"x": 1})
    store.save((2, "app"), {"b": {"verstr": "2"}}, set())
    store.purge_workspace(1)
    assert store.load((1, "app")) == {} and store.generation((1, "app")) == 0
    assert store.kv_get((1, "app"), "f") is None
    assert set(store.load((2, "app"))) == {"b"}
