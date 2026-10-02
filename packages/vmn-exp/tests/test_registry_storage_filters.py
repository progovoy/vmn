"""Tests for C5: artifact_uri per backend and the registry area never showing in app listings."""
import os

import boto3
import pytest
from moto import mock_aws

from vmn_exp.registry.store import ensure_model
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.ui.readers.experiments import list_apps, list_apps_from_storage
from vmn_exp.storage.areas import local_store_root

BUCKET = "vmn-test-bucket"
PREFIX = "exps"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x",
        AWS_SECRET_ACCESS_KEY="x",
        AWS_DEFAULT_REGION="us-east-1",
    ).items():
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------------------
# artifact_uri — local backend
# ---------------------------------------------------------------------------


def test_artifact_uri_local(tmp_path):
    storage = open_storage(root=local_store_root(str(tmp_path)), area="runs")
    uri = storage.artifact_uri("myapp", "0.0.1-dev.abc", "artifacts/model.pkl")
    assert uri.startswith("file://")
    assert "myapp" in uri
    assert "0.0.1-dev.abc" in uri
    assert "model.pkl" in uri
    assert "artifacts" in uri


# ---------------------------------------------------------------------------
# artifact_uri — S3 backend
# ---------------------------------------------------------------------------


def test_artifact_uri_s3():
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        storage = S3SnapshotStorage(BUCKET, prefix=PREFIX)
        uri = storage.artifact_uri("myapp", "0.0.1-dev.abc", "artifacts/model.pkl")
    assert uri == f"s3://{BUCKET}/{PREFIX}/myapp/0.0.1-dev.abc/artifacts/model.pkl"


# ---------------------------------------------------------------------------
# registry scopes (model names) never listed as apps
# ---------------------------------------------------------------------------


def test_local_list_apps_ignores_registry(tmp_path):
    root = str(tmp_path)
    storage = open_storage(root=local_store_root(root), area="runs")
    storage.save("myapp", "0.0.1", {"verstr": "0.0.1"}, {})
    ensure_model(storage, "resnet")
    assert storage.list_apps() == ["myapp"]


def test_ui_list_apps_ignores_registry(tmp_path):
    root = str(tmp_path)
    app_dir = os.path.join(root, ".vmn", "myapp")
    os.makedirs(app_dir)
    with open(os.path.join(app_dir, "conf.yml"), "w") as f:
        f.write("{}\n")
    ensure_model(open_storage(root=local_store_root(root), area="runs"), "resnet")
    names = [r["name"] for r in list_apps(root)]
    assert "myapp" in names
    assert "resnet" not in names


def test_ui_list_apps_from_storage_ignores_registry():
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        storage = S3SnapshotStorage(BUCKET, prefix=PREFIX)
        storage.save("myapp", "0.0.1", {"verstr": "0.0.1"}, {})
        ensure_model(storage, "resnet")
        rows = list_apps_from_storage(storage)
    names = [r["name"] for r in rows]
    assert names == ["myapp"]
