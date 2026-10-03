"""Cache status/resync/metrics on ``vmn-exp ui --db postgresql://`` (the
workspace cache serves ElectedIndexes there)."""
import argparse
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.cli import build_server, server_app  # noqa: E402

APP = "app"
V = "0.0.1-dev.abc.r1"
CACHE = "/api/v1/workspaces/ws/cache"


@pytest.fixture
def client(tmp_path, pg_dsn):
    uri = f"file://{tmp_path}/store"
    open_storage(uri, area=RUNS).save(
        APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    path = tmp_path / "server.yml"
    path.write_text(f"db: {pg_dsn}\ndata_dir: {tmp_path / 'data'}\n"
                    f"workspaces:\n  - {{name: ws, store: \"{uri}\"}}\n")
    args = argparse.Namespace(host="127.0.0.1", port=8265, token=None, data_dir=None,
                              db=None, config=str(path), repo=None, store=None,
                              read_only=False, no_index=False, allowed_host=None)
    manager, cfg, cp = build_server(args, env={})
    c = TestClient(server_app(manager, cfg, cp, args, env={}, token="t"),
                   headers={"Authorization": "Bearer t"})
    assert c.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments").status_code == 200
    return c


def test_cache_status_reports_the_viewed_app(client):
    resp = client.get(f"{CACHE}/status")
    assert resp.status_code == 200
    assert resp.json()["apps"][APP]["records"] == 1


def test_plain_resync_and_metrics(client):
    assert client.post(f"{CACHE}/resync", headers={"Content-Type": "application/json"}
                       ).status_code == 202
    assert client.get("/metrics").status_code == 200


def test_full_resync_rebuilds_in_the_background(client):
    resp = client.post(f"{CACHE}/resync?full=true",
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 202
    deadline = time.monotonic() + 5
    while client.get(f"{CACHE}/status").json()["state"] == "rebuilding":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    status = client.get(f"{CACHE}/status").json()
    assert status["rebuilds"] == 1
    assert status["apps"][APP]["records"] == 1
    rows = client.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments").json()
    assert [r["verstr"] for r in rows] == [V]
