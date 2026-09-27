"""Tests for the C9 model registry UI backend.

Covers: list models, detail shape, register version, alias expect-mismatch,
read-only 403, foreign Origin rejection, and /meta read_only field.
"""
import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _client(tmp_path, read_only=False):
    """Build a TestClient over a WorkspaceManager pointing at a tmp dir."""
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    # attach_path requires .git or .vmn
    vmn_dir = tmp_path / ".vmn"
    vmn_dir.mkdir()

    data_dir = tmp_path / "ui_data"
    data_dir.mkdir()
    manager = WorkspaceManager(str(data_dir))
    manager.attach_path("main", str(tmp_path))
    return TestClient(create_app(manager, read_only=read_only))


def _register(client, model, run_app="myapp", run_verstr="1.0.0-dev.abc"):
    """Register a new model version; returns (status_code, json)."""
    r = client.post(
        f"/api/v1/workspaces/main/models/{model}/versions",
        json={"run": {"app": run_app, "verstr": run_verstr}},
    )
    return r.status_code, r.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_models_empty(tmp_path):
    """GET /models with no registered models returns an empty list."""
    client = _client(tmp_path)
    r = client.get("/api/v1/workspaces/main/models")
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert data["models"] == []


def test_model_detail_shape_matches_contract(tmp_path):
    """Detail response has all keys from the TS ModelDetail contract."""
    client = _client(tmp_path)
    _register(client, "mymodel")

    r = client.get("/api/v1/workspaces/main/models/mymodel")
    assert r.status_code == 200
    detail = r.json()

    # Top-level keys from ModelDetail interface
    assert "name" in detail
    assert "description" in detail
    assert "versions" in detail
    assert "aliases" in detail
    assert "audit" in detail

    # versions array has ModelVersion keys
    assert len(detail["versions"]) == 1
    v = detail["versions"][0]
    assert "version" in v
    assert "status" in v
    assert "run" in v
    assert "artifact_path" in v
    assert "artifact_uri" in v
    assert "aliases" in v
    assert "created" in v
    assert "description" in v

    # run has app and verstr
    assert "app" in v["run"]
    assert "verstr" in v["run"]


def test_register_version_then_detail_shows_it(tmp_path):
    """POST register returns version number; GET detail shows the version."""
    client = _client(tmp_path)
    status, body = _register(client, "resnet50", "vision", "2.0.0-dev.abc123")

    assert status == 201
    assert "version" in body
    version_num = body["version"]
    assert isinstance(version_num, int)
    assert version_num >= 1

    r = client.get("/api/v1/workspaces/main/models/resnet50")
    assert r.status_code == 200
    detail = r.json()
    assert detail["name"] == "resnet50"
    assert len(detail["versions"]) == 1
    v = detail["versions"][0]
    assert v["version"] == version_num
    assert v["run"]["app"] == "vision"
    assert v["run"]["verstr"] == "2.0.0-dev.abc123"
    assert v["status"] == "active"


def test_register_increments_version_number(tmp_path):
    """Two POSTs give version 1 and version 2."""
    client = _client(tmp_path)
    s1, b1 = _register(client, "bert")
    s2, b2 = _register(client, "bert", run_verstr="1.1.0-dev.def")

    assert s1 == 201 and s2 == 201
    assert b1["version"] == 1
    assert b2["version"] == 2

    r = client.get("/api/v1/workspaces/main/models/bert")
    assert len(r.json()["versions"]) == 2


def test_alias_move_expect_mismatch_returns_409(tmp_path):
    """POST alias with wrong expect value → 409."""
    client = _client(tmp_path)
    _register(client, "gpt2")

    # First: assign alias to version 1 (no expect)
    r = client.post(
        "/api/v1/workspaces/main/models/gpt2/aliases",
        json={"alias": "production", "version": 1},
    )
    assert r.status_code == 200

    # Register a second version
    _register(client, "gpt2", run_verstr="2.0.0-dev.xyz")

    # Move alias with wrong expect (expect it points to version 2, but it points to 1)
    r = client.post(
        "/api/v1/workspaces/main/models/gpt2/aliases",
        json={"alias": "production", "version": 2, "expect": 99},
    )
    assert r.status_code == 409


def test_read_only_403_on_mutations(tmp_path):
    """All mutations return 403 in read-only mode."""
    # First register a model in read-write mode
    rw_client = _client(tmp_path, read_only=False)
    _register(rw_client, "mymodel")

    # Now test with read-only client
    ro_client = _client(tmp_path, read_only=True)

    mutations = [
        ("POST", "/api/v1/workspaces/main/models/mymodel/versions",
         {"run": {"app": "a", "verstr": "1.0.0-dev.abc"}}),
        ("POST", "/api/v1/workspaces/main/models/mymodel/aliases",
         {"alias": "prod", "version": 1}),
        ("DELETE", "/api/v1/workspaces/main/models/mymodel/aliases/prod", None),
        ("POST", "/api/v1/workspaces/main/models/mymodel/versions/1/status",
         {"status": "deprecated"}),
    ]
    for method, url, body in mutations:
        if method == "POST":
            r = ro_client.post(url, json=body)
        else:
            r = ro_client.delete(url)
        assert r.status_code == 403, f"{method} {url} should be 403, got {r.status_code}"


def test_foreign_origin_rejected(tmp_path):
    """POST with a foreign Origin header is refused (403)."""
    client = _client(tmp_path)
    r = client.post(
        "/api/v1/workspaces/main/models/mymodel/versions",
        json={"run": {"app": "a", "verstr": "1.0.0-dev.abc"}},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_meta_has_read_only(tmp_path):
    """/meta exposes a read_only field."""
    rw_client = _client(tmp_path, read_only=False)
    r = rw_client.get("/api/v1/meta")
    assert r.status_code == 200
    data = r.json()
    assert "read_only" in data
    assert data["read_only"] is False

    ro_client = _client(tmp_path, read_only=True)
    r = ro_client.get("/api/v1/meta")
    assert r.status_code == 200
    assert r.json()["read_only"] is True


def test_list_models_shows_registered(tmp_path):
    """GET /models shows a model after a version is registered."""
    client = _client(tmp_path)
    _register(client, "xlnet")

    r = client.get("/api/v1/workspaces/main/models")
    assert r.status_code == 200
    models = r.json()["models"]
    names = [m["name"] for m in models]
    assert "xlnet" in names

    row = next(m for m in models if m["name"] == "xlnet")
    # ModelRow keys from TS contract
    assert "description" in row
    assert "latest_version" in row
    assert "aliases" in row
    assert "versions_count" in row
    assert "updated" in row
    assert row["versions_count"] == 1
    assert row["latest_version"] == 1


def test_invalid_model_name_returns_400(tmp_path):
    """Registering with a name containing '-' returns 400."""
    client = _client(tmp_path)
    r = client.post(
        "/api/v1/workspaces/main/models/bad-name/versions",
        json={"run": {"app": "a", "verstr": "1.0.0-dev.abc"}},
    )
    assert r.status_code == 400


def test_get_nonexistent_model_returns_404(tmp_path):
    """GET /models/missing returns 404."""
    client = _client(tmp_path)
    r = client.get("/api/v1/workspaces/main/models/missing")
    assert r.status_code == 404


def test_set_version_status(tmp_path):
    """POST /versions/{n}/status changes the version's status."""
    client = _client(tmp_path)
    _register(client, "statusmodel")

    r = client.post(
        "/api/v1/workspaces/main/models/statusmodel/versions/1/status",
        json={"status": "deprecated"},
    )
    assert r.status_code == 200

    detail = client.get("/api/v1/workspaces/main/models/statusmodel").json()
    assert detail["versions"][0]["status"] == "deprecated"


def test_remove_alias(tmp_path):
    """DELETE alias removes it from the model."""
    client = _client(tmp_path)
    _register(client, "rmtest")

    # Add alias
    r = client.post(
        "/api/v1/workspaces/main/models/rmtest/aliases",
        json={"alias": "prod", "version": 1},
    )
    assert r.status_code == 200

    # Remove alias
    r = client.delete("/api/v1/workspaces/main/models/rmtest/aliases/prod")
    assert r.status_code == 200

    detail = client.get("/api/v1/workspaces/main/models/rmtest").json()
    assert "prod" not in detail["aliases"]
