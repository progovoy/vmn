"""Backend tests for env / inputs / imported_from fields in experiment detail.

4 tests (TDD — red first, then implementation):
- test_env_full:            env.yml present and small → full dict in response
- test_env_truncated_summary: env.yml large → metadata summary with truncated:true
- test_inputs_present:      input log entries → dict name→{uri,digest,kind}
- test_imported_from:       imported_from in metadata → returned; absent → null
"""
import json
import os

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

API = "/api/v1/workspaces/main/apps"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exp_dir(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr
    )
    os.makedirs(path, exist_ok=True)
    return path


def _write_meta(path, verstr, extra=None):
    meta = {
        "verstr": verstr,
        "code_verstr": verstr,
        "timestamp": "2026-09-27T10:00:00Z",
        "branch": "master",
        "base_version": "0.0.1",
    }
    if extra:
        meta.update(extra)
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f, sort_keys=True)


def _write_log(path, entries, writer="w0"):
    log_path = os.path.join(path, f"log/{writer}.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _client(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager, use_index=False))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_env_full(app_layout):
    """env.yml present and <= 256 KB → detail includes the full env dict."""
    verstr = "0.0.1-exp.1"
    path = _exp_dir(app_layout, verstr)
    env_data = {
        "python": {"version": "3.11.0", "implementation": "CPython"},
        "platform": {"system": "Linux", "machine": "x86_64"},
        "packages": {"torch": "2.0.0", "numpy": "1.24.0"},
        "hostname": "trainingbox",
    }
    _write_meta(path, verstr, extra={"env": {"python": "3.11.0", "packages_count": 2}})
    with open(os.path.join(path, "env.yml"), "w") as f:
        yaml.dump(env_data, f)
    _write_log(path, [{"type": "create", "timestamp": "2026-09-27T10:00:00Z"}])

    client = _client(app_layout)
    r = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}")
    assert r.status_code == 200
    detail = r.json()

    assert detail["env"] is not None
    assert detail["env"].get("truncated") is not True
    assert detail["env"]["python"]["version"] == "3.11.0"
    assert detail["env"]["packages"]["torch"] == "2.0.0"


def test_env_truncated_summary(app_layout):
    """env.yml > 256 KB → detail includes the metadata summary + truncated:true."""
    verstr = "0.0.1-exp.2"
    path = _exp_dir(app_layout, verstr)
    # Build a large env.yml (> 256 KB)
    big_packages = {f"pkg-{i}": f"1.{i}.0" for i in range(20000)}
    env_data = {
        "python": {"version": "3.10.0"},
        "platform": {"system": "Darwin", "machine": "arm64"},
        "packages": big_packages,
    }
    summary = {"python": "3.10.0", "platform": "Darwin/arm64", "packages_count": 20000}
    _write_meta(path, verstr, extra={"env": summary})
    with open(os.path.join(path, "env.yml"), "w") as f:
        yaml.dump(env_data, f)
    _write_log(path, [{"type": "create", "timestamp": "2026-09-27T10:00:01Z"}])

    client = _client(app_layout)
    r = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}")
    assert r.status_code == 200
    detail = r.json()

    assert detail["env"] is not None
    assert detail["env"]["truncated"] is True
    assert detail["env"]["python"] == "3.10.0"


def test_inputs_present(app_layout):
    """Input log entries fold to {name: {uri, digest, kind}} in detail."""
    verstr = "0.0.1-exp.3"
    path = _exp_dir(app_layout, verstr)
    _write_meta(path, verstr)
    _write_log(path, [
        {"type": "create", "timestamp": "2026-09-27T10:00:02Z"},
        {
            "type": "input",
            "timestamp": "2026-09-27T10:00:03Z",
            "name": "train_data",
            "uri": "s3://bucket/data.csv",
            "digest": "sha256:abc123",
            "kind": "dataset",
        },
        {
            "type": "input",
            "timestamp": "2026-09-27T10:00:04Z",
            "name": "val_data",
            "uri": "gs://bucket/val.csv",
            "digest": None,
            "kind": "dataset",
        },
    ])

    client = _client(app_layout)
    r = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}")
    assert r.status_code == 200
    detail = r.json()

    assert detail["inputs"] is not None
    assert "train_data" in detail["inputs"]
    assert detail["inputs"]["train_data"]["uri"] == "s3://bucket/data.csv"
    assert detail["inputs"]["train_data"]["digest"] == "sha256:abc123"
    assert detail["inputs"]["train_data"]["kind"] == "dataset"
    assert "val_data" in detail["inputs"]


def test_imported_from(app_layout):
    """imported_from present in metadata → in detail; absent in old run → null."""
    verstr_new = "0.0.1-exp.4"
    verstr_old = "0.0.1-exp.5"

    path_new = _exp_dir(app_layout, verstr_new)
    _write_meta(
        path_new, verstr_new,
        extra={"imported_from": "mlflow:abc123456789"},
    )
    _write_log(path_new, [{"type": "create", "timestamp": "2026-09-27T10:00:05Z"}])

    path_old = _exp_dir(app_layout, verstr_old)
    _write_meta(path_old, verstr_old)
    _write_log(path_old, [{"type": "create", "timestamp": "2026-09-27T10:00:06Z"}])

    client = _client(app_layout)

    r = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr_new}")
    assert r.status_code == 200
    assert r.json()["imported_from"] == "mlflow:abc123456789"

    r = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr_old}")
    assert r.status_code == 200
    assert r.json()["imported_from"] is None
