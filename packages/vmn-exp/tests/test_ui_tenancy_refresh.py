"""Background cache work runs in the workspace's org (plan 11 §6.3): a
refresher thread has no request org, so each workspace app's cache keeps the
org of the request that opened it."""
import threading

import pytest

pytest.importorskip("psycopg")

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.tenancy import org_context  # noqa: E402

APP = "app"
V = "0.0.1-dev.abc.r1"


class _Ws:
    def __init__(self, name, store):
        self.name, self.store = name, store


def _seed(tmp_path):
    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return _Ws("ws", uri), storage


def _in_thread(fn):
    thread = threading.Thread(target=fn)
    thread.start()
    thread.join()


def test_a_refresh_off_the_request_writes_under_the_workspace_org(tmp_path, pg_rls_dsn):
    from vmn_exp.ui.cache_pg import PostgresStore
    from vmn_exp.ui.pg_mode import PgIndexes, workspace_id
    from vmn_exp.ui.refresher import InlineRefresher

    ws, storage = _seed(tmp_path)
    pg = PgIndexes(pg_rls_dsn, InlineRefresher())
    try:
        with org_context(2):
            index = pg.index(ws, APP, storage)
        _in_thread(index.refresh)
        store = PostgresStore(pg_rls_dsn)
        with org_context(2):
            assert set(store.load((workspace_id(ws), APP))) == {V}
        with org_context(1):
            assert store.load((workspace_id(ws), APP)) == {}
    finally:
        pg.close()


def test_orgs_sharing_a_workspace_name_get_their_own_index(tmp_path, pg_rls_dsn):
    from vmn_exp.ui.pg_mode import PgIndexes
    from vmn_exp.ui.refresher import InlineRefresher

    ws, storage = _seed(tmp_path)
    pg = PgIndexes(pg_rls_dsn, InlineRefresher())
    try:
        with org_context(1):
            a = pg.index(ws, APP, storage)
        with org_context(2):
            b = pg.index(ws, APP, storage)
        assert a is not b
    finally:
        pg.close()
