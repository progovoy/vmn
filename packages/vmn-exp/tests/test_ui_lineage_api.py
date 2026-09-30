"""``GET .../experiments/{verstr}/lineage`` — upstream/downstream runs and models."""
import json
import os

import pytest
import yaml
from exp_helpers import _storage

from vmn_exp.core.lineage import artifact_ref_uri

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

API = "/api/v1/workspaces/main/apps"
SHA = "d" * 64


def _write_run(app_layout, verstr, entries, second):
    path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr)
    os.makedirs(path, exist_ok=True)
    meta = {
        "verstr": verstr, "code_verstr": verstr, "branch": "master", "base_version": "0.0.1",
        "timestamp": f"2026-09-27T10:00:0{second}Z", "name": verstr.split(".")[-1],
    }
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    with open(os.path.join(path, "log.w0.jsonl"), "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _chain(app_layout):
    app = app_layout.app_name
    ts = "2026-09-27T10:00:00Z"
    _write_run(app_layout, "0.0.1-exp.prep", [
        {"type": "artifact", "timestamp": ts, "path": "data.csv", "sha256": SHA, "size": 3},
    ], 1)
    _write_run(app_layout, "0.0.1-exp.train", [
        {"type": "input", "ts": ts, "name": "data", "uri": "file:///d.csv",
         "digest": f"sha256:{SHA}", "kind": None},
        {"type": "artifact", "timestamp": ts, "path": "model.pkl", "sha256": "e" * 64, "size": 1},
    ], 2)
    _write_run(app_layout, "0.0.1-exp.eval", [
        {"type": "input", "ts": ts, "name": "model", "kind": "artifact", "digest": None,
         "uri": artifact_ref_uri(app, "0.0.1-exp.train", "model.pkl")},
    ], 3)


@pytest.fixture(params=[False, True], ids=["direct", "index"])
def client(request, app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    _chain(app_layout)
    return TestClient(create_app(manager, use_index=request.param))


def _get(client, app_layout, verstr, **params):
    return client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}/lineage", params=params)


def test_upstream_and_downstream(client, app_layout):
    resp = _get(client, app_layout, "0.0.1-exp.train")
    assert resp.status_code == 200
    body = resp.json()
    assert body["verstr"] == "0.0.1-exp.train"
    assert [(n["verstr"], n["status"]) for n in body["upstream"]] == [("0.0.1-exp.prep", "created")]
    assert body["upstream"][0]["links"][0]["via"] == "digest"
    assert [n["verstr"] for n in body["downstream"]] == ["0.0.1-exp.eval"]
    assert body["models"] == [] and body["truncated"] is False


def test_depth(client, app_layout):
    body = _get(client, app_layout, "0.0.1-exp.eval", depth=2).json()
    assert [(n["verstr"], n["depth"]) for n in body["upstream"]] == [
        ("0.0.1-exp.train", 1), ("0.0.1-exp.prep", 2),
    ]


def test_models(client, app_layout):
    from vmn_exp.registry.store import ensure_model, register_version

    storage = _storage(app_layout)
    ensure_model(storage, "clf")
    register_version(
        storage, "clf", run_ref={"app": app_layout.app_name, "verstr": "0.0.1-exp.train"},
        artifact_path="model.pkl",
    )
    body = _get(client, app_layout, "0.0.1-exp.train").json()
    assert [(m["model"], m["version"]) for m in body["models"]] == [("clf", 1)]


def test_unknown_run_is_404(client, app_layout):
    assert _get(client, app_layout, "0.0.1-exp.nope").status_code == 404


def test_an_unsafe_verstr_is_400(client, app_layout):
    resp = _get(client, app_layout, "a%5Cb")
    assert resp.status_code == 400
    assert "Invalid version" in resp.json()["detail"]


def test_bad_depth_is_400(client, app_layout):
    assert _get(client, app_layout, "0.0.1-exp.train", depth=0).status_code == 400


def test_uri_into_an_unknown_app(client, app_layout):
    _write_run(app_layout, "0.0.1-exp.ghost", [
        {"type": "input", "ts": "2026-09-27T10:00:00Z", "name": "x", "kind": None,
         "digest": None, "uri": artifact_ref_uri("ghost_app", "1.0.0", "x.bin")},
    ], 4)
    body = _get(client, app_layout, "0.0.1-exp.ghost").json()
    assert [(n["app"], n["verstr"], n["found"]) for n in body["upstream"]] == [
        ("ghost_app", "1.0.0", False)
    ]
