"""Two workspaces sharing an app name are separate election and wake scopes."""
import time

import pytest

pytest.importorskip("psycopg")

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.refresher import InlineRefresher, Refresher  # noqa: E402

APP = "app"


class _Ws:
    def __init__(self, name, store):
        self.name, self.store = name, store


def _seed(tmp_path, name):
    uri = f"file://{tmp_path}/{name}"
    storage = open_storage(uri, area=RUNS)
    verstr = f"0.0.1-dev.abc.{name}"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return _Ws(name, uri), storage, verstr


def test_replicas_lead_their_own_workspace_of_a_shared_app_name(tmp_path, pg_dsn):
    from vmn_exp.ui.pg_mode import PgIndexes

    a, b = PgIndexes(pg_dsn, InlineRefresher()), PgIndexes(pg_dsn, InlineRefresher())
    try:
        ws1, st1, v1 = _seed(tmp_path, "ws1")
        ws2, st2, v2 = _seed(tmp_path, "ws2")
        i1 = a.index(ws1, APP, st1).refresh()
        i2 = b.index(ws2, APP, st2).refresh()
        assert i1.leading and i2.leading
        assert [r["verstr"] for r in i2.snapshot().rows] == [v2]
    finally:
        a.close()
        b.close()


def test_elected_index_wake_key_carries_its_workspace(tmp_path, pg_dsn):
    from vmn_exp.ui.pg_mode import PgIndexes, workspace_id

    pg = PgIndexes(pg_dsn, InlineRefresher())
    try:
        ws1, st1, _ = _seed(tmp_path, "ws1")
        assert pg.index(ws1, APP, st1).wake_key == f"{workspace_id(ws1)}:{APP}"
    finally:
        pg.close()


class _Counting:
    def __init__(self, wake_key):
        self.app_name = APP
        self.wake_key = wake_key
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1
        return self

    def snapshot(self):
        return None


def _until(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_wake_scope_wakes_only_the_matching_workspace():
    one, two = _Counting(f"1:{APP}"), _Counting(f"2:{APP}")
    refresher = Refresher(interval_sec=30)
    try:
        refresher.snapshot(one)
        refresher.snapshot(two)
        _until(lambda: one.refreshes == 1 and two.refreshes == 1)
        refresher.wake_scope(f"1:{APP}")
        _until(lambda: one.refreshes == 2)
        time.sleep(0.3)
        assert two.refreshes == 1
    finally:
        refresher.stop()
