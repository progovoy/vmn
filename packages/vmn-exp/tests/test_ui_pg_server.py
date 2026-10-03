"""``vmn-exp ui --db postgresql://...`` (plan 11 §4, §6.3, §7): the control
plane, store workspaces' cache and search live in Postgres; tenancy reaches
the workspace manager and turns row-level security on."""
import argparse

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.cli import build_server, open_control_plane, server_app  # noqa: E402

APP = "app"
V = "0.0.1-dev.abc.r1"


def _args(tmp_path, text, **kw):
    path = tmp_path / "server.yml"
    path.write_text(text)
    base = dict(host="127.0.0.1", port=8265, token=None, data_dir=None, db=None,
                config=str(path), repo=None, store=None, read_only=False,
                no_index=False, allowed_host=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _config(tmp_path, dsn, tenancy="single", store=None):
    text = f"server: {{tenancy: {tenancy}}}\ndb: {dsn}\ndata_dir: {tmp_path / 'data'}\n"
    if store:
        text += f"workspaces:\n  - {{name: ws, store: \"{store}\"}}\n"
    return _args(tmp_path, text)


def _query(dsn, sql):
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql).fetchall()


def _rls_on(dsn, table):
    return _query(dsn, f"SELECT relrowsecurity FROM pg_class WHERE relname = '{table}'")[0][0]


def test_postgres_dsn_opens_the_postgres_control_plane(tmp_path, pg_dsn):
    from vmn_exp.ui.control_plane_pg import PostgresControlPlane

    cfg = argparse.Namespace(db=pg_dsn, data_dir=str(tmp_path))
    assert isinstance(open_control_plane(cfg), PostgresControlPlane)


def test_workspaces_seed_into_postgres(tmp_path, pg_dsn):
    manager, _, _ = build_server(_config(tmp_path, pg_dsn, store="file:///tmp/s"), env={})
    assert manager.get("ws").store == "file:///tmp/s"
    assert _query(pg_dsn, "SELECT count(*) FROM vmn_workspaces")[0][0] == 1


def test_multi_tenancy_reaches_the_manager_and_enables_rls(tmp_path, pg_dsn):
    manager, _, _ = build_server(_config(tmp_path, pg_dsn, tenancy="multi"), env={})
    assert manager.tenancy == "multi"
    assert _rls_on(pg_dsn, "vmn_records") and _rls_on(pg_dsn, "vmn_workspaces")


def test_single_tenancy_leaves_rls_off(tmp_path, pg_dsn):
    manager, _, _ = build_server(_config(tmp_path, pg_dsn), env={})
    assert manager.tenancy == "single"
    assert not _rls_on(pg_dsn, "vmn_records")


@pytest.fixture
def client(tmp_path, pg_dsn):
    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    args = _config(tmp_path, pg_dsn, store=uri)
    manager, cfg, cp = build_server(args, env={})
    app = server_app(manager, cfg, cp, args, env={}, token="t")
    return TestClient(app, headers={"Authorization": "Bearer t"})


def test_store_workspace_rows_are_cached_in_postgres(client, pg_dsn):
    body = client.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments").json()
    assert [r["verstr"] for r in body] == [V]
    assert _query(pg_dsn, "SELECT app, key FROM vmn_records") == [(APP, V)]


def test_search_pushes_down_to_postgres(client, pg_dsn):
    body = client.get("/api/v1/search", params={"q": f'verstr = "{V}"'}).json()
    assert [r["verstr"] for r in body["results"]] == [V]
    assert _query(pg_dsn, "SELECT workspace, app, verstr FROM vmn_search_rows") == [
        ("ws", APP, V)]


class _Ws:
    def __init__(self, name, store):
        self.name, self.store = name, store


def _seed(tmp_path, name, verstr):
    uri = f"file://{tmp_path}/{name}"
    storage = open_storage(uri, area=RUNS)
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return _Ws(name, uri), storage


def test_replicas_elect_one_leader_per_workspace_app(tmp_path, pg_dsn):
    from vmn_exp.ui.pg_mode import PgIndexes
    from vmn_exp.ui.refresher import InlineRefresher

    ws, storage = _seed(tmp_path, "ws", V)
    replicas = [PgIndexes(pg_dsn, InlineRefresher()) for _ in range(2)]
    try:
        indexes = [r.index(ws, APP, storage).refresh() for r in replicas]
        assert sorted(i.leading for i in indexes) == [False, True]
        rows = [[row["verstr"] for row in i.refresh().snapshot().rows] for i in indexes]
        assert rows == [[V], [V]]
    finally:
        for r in replicas:
            r.close()


def test_workspaces_sharing_an_app_name_get_their_own_scope(tmp_path, pg_dsn):
    from vmn_exp.ui.pg_mode import PgIndexes
    from vmn_exp.ui.refresher import InlineRefresher

    pg = PgIndexes(pg_dsn, InlineRefresher())
    try:
        for name in ("a", "b"):
            ws, storage = _seed(tmp_path, name, f"0.0.1-dev.abc.{name}")
            pg.index(ws, APP, storage).refresh()
        rows = _query(pg_dsn, "SELECT workspace_id, key FROM vmn_records ORDER BY key")
        assert [k for _, k in rows] == ["0.0.1-dev.abc.a", "0.0.1-dev.abc.b"]
        assert rows[0][0] != rows[1][0]
    finally:
        pg.close()
