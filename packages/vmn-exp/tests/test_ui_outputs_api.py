"""Run outputs over HTTP: list/leaderboard pages never carry them (a run
logging an image per step would bloat every row at 100k runs), yet ``?q=``
over ``outputs.*`` filters, the run detail lists them and lineage links by
them."""
import json
import os

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

API = "/api/v1/workspaces/main/apps"
SHA = "f" * 64
QUERY = 'outputs."media/x/0.png".size > 0'


def _write(app_layout, verstr, second, entries):
    path = os.path.join(app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr)
    os.makedirs(path, exist_ok=True)
    meta = {"verstr": verstr, "code_verstr": verstr, "branch": "master",
            "base_version": "0.0.1", "timestamp": f"2026-09-21T12:00:0{second}Z"}
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    os.makedirs(os.path.dirname(os.path.join(path, "log/w0.jsonl")), exist_ok=True)
    with open(os.path.join(path, "log/w0.jsonl"), "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _seed(app_layout):
    ts = "2026-09-21T12:05:00Z"
    _write(app_layout, "0.0.1", 1, [
        {"timestamp": ts, "type": "image", "name": "x", "step": 0,
         "path": "media/x/0.png", "sha256": SHA, "size": 5},
        {"timestamp": ts, "type": "metrics", "values": {"loss": 0.5}},
    ])
    _write(app_layout, "0.0.2", 2, [
        {"timestamp": ts, "type": "input", "name": "pic", "uri": "file:///p.png",
         "digest": f"sha256:{SHA}", "kind": None},
        {"timestamp": ts, "type": "metrics", "values": {"loss": 0.4}},
    ])


@pytest.fixture(params=[True, False], ids=["index", "direct"])
def client(request, app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    _seed(app_layout)
    return TestClient(create_app(manager, use_index=request.param))


def _url(app_layout, tail=""):
    return f"{API}/{app_layout.app_name}/experiments{tail}"


def _rows(body):
    return body["rows"] if isinstance(body, dict) else body


def test_list_pages_do_not_carry_outputs(client, app_layout):
    for params in ({}, {"limit": 10}, {"sort": "loss", "limit": 10}, {"last": 1}):
        resp = client.get(_url(app_layout), params=params)
        assert resp.status_code == 200, resp.text
        rows = _rows(resp.json())
        assert rows and all("outputs" not in row for row in rows)


def test_query_over_outputs_filters_the_list(client, app_layout):
    resp = client.get(_url(app_layout), params={"q": QUERY, "limit": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["verstr"] for r in body["rows"]] == ["0.0.1"] and body["total"] == 1
    assert "outputs" not in body["rows"][0]
    negated = _rows(client.get(_url(app_layout), params={"q": f"not {QUERY}"}).json())
    assert [r["verstr"] for r in negated] == ["0.0.2"]


def test_run_detail_lists_its_outputs(client, app_layout):
    body = client.get(_url(app_layout, "/0.0.1")).json()
    assert body["outputs"] == {
        "media/x/0.png": {"path": "media/x/0.png", "digest": f"sha256:{SHA}", "size": 5}
    }


def test_lineage_links_a_media_consumer_by_digest(client, app_layout):
    body = client.get(_url(app_layout, "/0.0.1/lineage")).json()
    assert [(n["verstr"], n["links"][0]["artifact"]) for n in body["downstream"]] == [
        ("0.0.2", "media/x/0.png")
    ]
