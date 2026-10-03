"""Run detail carries a fork's origin and a run's rewinds; its series skip
what a rewind hides."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

API = "/api/v1/workspaces/main/apps"


def _record(app_layout, verstr, entries, meta=None):
    path = os.path.join(app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr)
    os.makedirs(path, exist_ok=True)
    metadata = {"verstr": verstr, "code_verstr": verstr, "branch": "master",
                "timestamp": "2026-09-27T10:00:00Z", "base_version": "0.0.1"}
    metadata.update(meta or {})
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump({"format_version": 1, **metadata}, f, sort_keys=True)
    os.makedirs(os.path.dirname(os.path.join(path, "log/w0.jsonl")), exist_ok=True)
    with open(os.path.join(path, "log/w0.jsonl"), "a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _client(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager, use_index=False))


def _m(sec, step, loss):
    return {"type": "metrics", "timestamp": f"2026-09-27T10:00:{sec:02d}Z",
            "step": step, "values": {"loss": loss}}


def test_detail_reports_fork_origin_and_rewinds(app_layout):
    _record(app_layout, "0.0.1-exp.1", [
        _m(1, 1, 1.0), _m(2, 2, 0.5),
        {"type": "rewind", "timestamp": "2026-09-27T10:00:03Z", "step": 1},
        _m(4, 2, 0.7),
    ])
    _record(app_layout, "0.0.1-exp.2", [_m(5, 1, 1.0)],
            meta={"forked_from": {"verstr": "0.0.1-exp.1", "step": 1}})
    client = _client(app_layout)

    source = client.get(f"{API}/{app_layout.app_name}/experiments/0.0.1-exp.1").json()
    assert source["forked_from"] is None
    assert [r["step"] for r in source["rewinds"]] == [1]
    assert [(p["step"], p["value"]) for p in source["series"]["loss"]] == [(1, 1.0), (2, 0.7)]

    fork = client.get(f"{API}/{app_layout.app_name}/experiments/0.0.1-exp.2").json()
    assert fork["forked_from"] == {"verstr": "0.0.1-exp.1", "step": 1}
    assert fork["rewinds"] == []
