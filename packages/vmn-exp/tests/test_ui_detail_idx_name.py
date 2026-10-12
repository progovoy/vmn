"""Run detail carries the resolved run's storage index and name, so the
shell's run crumb reads ``@54 lr-sweep-3`` (plan 19 §2.1)."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"
RUNS_ = [
    ("0.0.1-dev.aaaa1111.1", "first"),
    ("0.0.1-dev.bbbb2222.2", None),
    ("0.0.1-dev.cccc3333.3", "third"),
]


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for i, (v, name) in enumerate(RUNS_):
        meta = {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}
        if name:
            meta["name"] = name
        storage.save(APP, v, meta, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def _detail(client, ref):
    r = client.get(f"{BASE}/{ref}", params={"series": "false"})
    assert r.status_code == 200, r.text
    return r.json()


def _idx_of(client):
    rows = client.get(BASE, params={"limit": 10}).json()["rows"]
    return {row["verstr"]: row["idx"] for row in rows}


def test_full_verstr(client):
    idx = _idx_of(client)
    body = _detail(client, RUNS_[0][0])
    assert body["idx"] == idx[RUNS_[0][0]]
    assert body["name"] == "first"


def test_at_n_ref(client):
    idx = _idx_of(client)
    verstr = RUNS_[2][0]
    body = _detail(client, f"@{idx[verstr]}")
    assert body["metadata"]["verstr"] == verstr
    assert body["idx"] == idx[verstr]
    assert body["name"] == "third"


def test_prefix_ref(client):
    idx = _idx_of(client)
    body = _detail(client, "0.0.1-dev.bbbb")
    assert body["metadata"]["verstr"] == RUNS_[1][0]
    assert body["idx"] == idx[RUNS_[1][0]]
    assert body["name"] is None


def test_latest_ref(client):
    idx = _idx_of(client)
    body = _detail(client, "latest")
    verstr = body["metadata"]["verstr"]
    assert body["idx"] == idx[verstr]
    assert body["name"] == dict(RUNS_)[verstr]


def test_without_a_child_row_reader_idx_is_null(tmp_path):
    from vmn_exp.ui.readers.experiment_detail import experiment_detail

    storage = open_storage(f"file://{tmp_path}/store", area=RUNS)
    storage.save(APP, RUNS_[0][0], {"verstr": RUNS_[0][0], "name": "first"}, {})
    detail, err = experiment_detail(storage, APP, RUNS_[0][0], include_series=False)
    assert err is None
    assert detail["idx"] is None
    assert detail["name"] == "first"
