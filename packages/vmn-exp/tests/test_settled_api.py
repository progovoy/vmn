"""Over HTTP: an outer run that ended settles what it left behind — the app's
``experiments-status``, the outer run's ``summary`` and its run detail count
its never-started child as ``never_started`` and its stuck one as ``lost``,
not as waiting or stuck; the children's own status stays."""
import datetime
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
OUTER = "0.0.1-dev.0000abcd.0"


def _iso(sec_ago=0):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=sec_ago)).isoformat()


def _finished(code):
    return {"state": "finished", "exit_code": code, "started_at": _iso(7200),
            "finished_at": _iso(7000)}


STALE = {"state": "running", "started_at": _iso(7200), "heartbeat": _iso(7000),
         "heartbeat_interval_sec": 5}
KIDS = [None, STALE, _finished(0)]  # never started, lost, succeeded


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for i, state in enumerate([_finished(0)] + KIDS):
        v = f"0.0.1-dev.{i:04d}abcd.{i}"
        meta = {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
        if i:
            meta["parent"] = OUTER
        storage.save(APP, v, meta, {})
        if state is not None:
            storage.save_file(APP, v, "run_state.yml", yaml.dump(state))
    old = datetime.datetime.now().timestamp() - 7000  # no fresh store write: stuck
    for root, _, files in os.walk(tmp_path / "store"):
        for name in files:
            os.utime(os.path.join(root, name), (old, old))
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def _get(client, path):
    resp = client.get(f"{BASE}{path}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_app_status_counts_settled_runs_apart(client):
    body = _get(client, "/experiments-status")
    assert body["counts"] == {"created": 0, "running": 0, "stuck": 0, "succeeded": 2,
                              "failed": 0}
    assert (body["never_started"], body["lost"], body["total"]) == (1, 1, 4)
    assert body["rollup"] is None  # no stuck run needs a look


def test_the_outer_runs_summary_has_ended_with_nothing_waiting(client):
    body = _get(client, f"/experiments/{OUTER}/summary")
    assert body["ended"] is True and body["tree_status"] == "failed"
    assert (body["counts"]["waiting"], body["counts"]["stuck"]) == (0, 0)
    assert (body["never_started"], body["lost"], body["done"]) == (1, 1, 2)
    assert body["eta_sec"] == 0


def test_the_run_detail_fleet_and_the_childrens_own_status(client):
    fleet = _get(client, f"/experiments/{OUTER}")["status"]["fleet"]
    assert (fleet["never_started"], fleet["lost"]) == (1, 1)
    rows = _get(client, "/experiments?limit=10&q=settled%20!%3D%20null")["rows"]
    assert sorted((r["status"], r["settled"]) for r in rows) == [
        ("created", "never_started"), ("stuck", "lost")]
