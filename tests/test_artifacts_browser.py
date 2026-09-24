#!/usr/bin/env python3
"""Tests for Phase 4.2: Artifacts Browser — structured artifacts list and download endpoint."""
import os

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core.logging import init_stamp_logger
from version_stamp.ui.readers import experiments as exp_reader


@pytest.fixture(autouse=True)
def _init_logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _save_exp(storage, app, verstr, ts="2025-01-01T00:00:00Z"):
    """Save a minimal experiment."""
    storage.save(
        app,
        verstr,
        {
            "verstr": verstr,
            "app_name": app,
            "timestamp": ts,
            "base_version": "1.0.0",
            "base_commit": "abc1234",
            "branch": "main",
            "remote": None,
        },
        {},
    )


def _create_artifact(storage, app, verstr, filename, content):
    """Write an artifact file into the experiment's artifacts directory."""
    snap_dir = storage._snapshot_dir(app, verstr)
    art_dir = os.path.join(snap_dir, "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    path = os.path.join(art_dir, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


# -- Structured artifacts in experiment detail ---------------------------------


def test_experiment_detail_includes_structured_artifacts(tmp_path):
    """get_experiment_from_storage should return an 'artifacts' list with name and size."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    _save_exp(storage, "myapp", "1.0.0-dev.aaa.bbb")
    _create_artifact(storage, "myapp", "1.0.0-dev.aaa.bbb", "model.pt", "x" * 100)
    _create_artifact(
        storage, "myapp", "1.0.0-dev.aaa.bbb", "config.json", '{"lr": 0.01}'
    )

    result, err = exp_reader.get_experiment_from_storage(
        storage, "myapp", "1.0.0-dev.aaa.bbb"
    )

    assert err is None
    assert "artifacts" in result
    artifacts = result["artifacts"]
    assert isinstance(artifacts, list)
    assert len(artifacts) == 2

    names = sorted(a["name"] for a in artifacts)
    assert names == ["config.json", "model.pt"]

    for a in artifacts:
        assert "name" in a
        assert "size" in a
        assert isinstance(a["size"], int)
        assert a["size"] > 0


def test_experiment_detail_no_artifacts(tmp_path):
    """Experiment with no artifacts returns an empty artifacts list."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    _save_exp(storage, "myapp", "1.0.0-dev.aaa.bbb")

    result, err = exp_reader.get_experiment_from_storage(
        storage, "myapp", "1.0.0-dev.aaa.bbb"
    )

    assert err is None
    assert "artifacts" in result
    assert result["artifacts"] == []


def test_experiment_from_storage_includes_structured_artifacts(tmp_path):
    """get_experiment_from_storage also returns structured artifacts."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    _save_exp(storage, "myapp", "1.0.0-dev.aaa.bbb")
    _create_artifact(storage, "myapp", "1.0.0-dev.aaa.bbb", "weights.bin", "w" * 50)

    result, err = exp_reader.get_experiment_from_storage(
        storage, "myapp", "1.0.0-dev.aaa.bbb"
    )

    assert err is None
    assert "artifacts" in result
    assert len(result["artifacts"]) == 1
    assert result["artifacts"][0]["name"] == "weights.bin"
    assert result["artifacts"][0]["size"] == 50


# -- Download endpoint ---------------------------------------------------------

try:
    import fastapi as _fastapi  # noqa: F401

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


def _make_client(tmp_path):
    """Build a TestClient with a workspace pointing to tmp_path."""
    from fastapi.testclient import TestClient
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    data_dir = os.path.join(str(tmp_path), "ui_data")
    manager = WorkspaceManager(data_dir)
    manager.attach_path("test", str(tmp_path))
    app = create_app(manager, use_index=False)
    return TestClient(app)


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_artifact_download_returns_file(tmp_path):
    """GET /artifacts/{filename} returns the file content."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    _save_exp(storage, "myapp", "1.0.0-dev.aaa.bbb")
    _create_artifact(storage, "myapp", "1.0.0-dev.aaa.bbb", "output.csv", "a,b\n1,2\n")

    client = _make_client(tmp_path)
    r = client.get(
        "/api/v1/workspaces/test/apps/myapp/experiments/1.0.0-dev.aaa.bbb/artifacts/output.csv"
    )

    assert r.status_code == 200
    assert r.text == "a,b\n1,2\n"


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_artifact_download_not_found(tmp_path):
    """GET /artifacts/{filename} returns 404 for nonexistent files."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    _save_exp(storage, "myapp", "1.0.0-dev.aaa.bbb")

    client = _make_client(tmp_path)
    r = client.get(
        "/api/v1/workspaces/test/apps/myapp/experiments/1.0.0-dev.aaa.bbb/artifacts/noexist.txt"
    )

    assert r.status_code == 404
