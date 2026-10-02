"""``SnapshotStorage.list_apps()``: every backend names the apps it holds,
never the model registry (its own store area) — and a ``file://`` store workspace lists its apps."""
import os

import boto3
import pytest
from moto import mock_aws

from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.s3 import S3SnapshotStorage

REAL_APPS = ["my_app", "root/svc"]


def _record(storage, app, verstr="0.0.1-dev.abc"):
    storage.save(app, verstr, {"verstr": verstr, "app_name": app}, {})


def _fill(storage):
    for app in REAL_APPS:
        _record(storage, app)
    ensure_model(storage, "resnet")
    register_version(storage, "resnet", {"app": "my_app", "verstr": "0.0.1-dev.abc"})


def test_local_storage_lists_its_apps_without_registry(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    _fill(storage)
    assert storage.list_apps() == REAL_APPS


def test_local_storage_ignores_the_other_area(tmp_path):
    _record(LocalSnapshotStorage(str(tmp_path), area="snapshots"), "snap_only")
    assert LocalSnapshotStorage(str(tmp_path), area="runs").list_apps() == []


@pytest.fixture
def bucket(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="apps-bkt")
        yield "apps-bkt"


def test_s3_storage_lists_its_apps_without_registry(bucket):
    storage = S3SnapshotStorage(bucket, prefix="exps")
    _fill(storage)
    assert storage.list_apps() == REAL_APPS


def test_cached_storage_merges_local_and_remote_apps(bucket, tmp_path):
    storage = open_storage(f"s3://{bucket}/exps", str(tmp_path), area="runs")
    _record(storage._remote, "remote_app")
    _record(storage._local, "local_app")
    assert storage.list_apps() == ["local_app", "remote_app"]


def test_file_store_workspace_lists_its_apps(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    store_dir = tmp_path / "store"
    _fill(LocalSnapshotStorage(str(store_dir), area="runs"))
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", f"file://{os.path.abspath(store_dir)}")

    rows = TestClient(create_app(manager)).get("/api/v1/workspaces/ws/apps").json()

    assert [(r["name"], r["experiments"]) for r in rows] == [
        ("my_app", 1),
        ("root/svc", 1),
    ]
