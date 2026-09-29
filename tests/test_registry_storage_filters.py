"""Tests for C5: artifact_uri per backend and vmn-registry filtering in app listings."""
import os

import boto3
import pytest
from moto import mock_aws

from vmn_exp.snapshot import get_snapshot_storage
from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.sdk.reader import _apps_with_experiments
from vmn_exp.ui.readers.experiments import list_apps, list_apps_from_storage

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
    storage = get_snapshot_storage(
        "local", vmn_root_path=str(tmp_path), subdir="experiments"
    )
    uri = storage.artifact_uri("myapp", "0.0.1-dev.abc", "model.pkl")
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
        uri = storage.artifact_uri("myapp", "0.0.1-dev.abc", "model.pkl")
    assert uri == f"s3://{BUCKET}/{PREFIX}/myapp/0.0.1-dev.abc/artifacts/model.pkl"


# ---------------------------------------------------------------------------
# vmn-registry hidden from exp/reader._apps_with_experiments
# ---------------------------------------------------------------------------


def test_apps_with_experiments_ignores_registry(tmp_path):
    root = str(tmp_path)
    # Create a real app and the reserved registry pseudo-app
    for app in ("myapp", "vmn-registry"):
        exp_dir = os.path.join(root, ".vmn", app, "experiments")
        os.makedirs(exp_dir)

    apps = _apps_with_experiments(root)
    assert "myapp" in apps
    assert "vmn-registry" not in apps


# ---------------------------------------------------------------------------
# vmn-registry hidden from UI app listing (local)
# ---------------------------------------------------------------------------


def test_ui_list_apps_ignores_registry(tmp_path):
    root = str(tmp_path)
    # Seed local app structure — conf.yml is enough to register an app
    for app in ("myapp", "vmn-registry"):
        app_dir = os.path.join(root, ".vmn", app)
        os.makedirs(app_dir)
        with open(os.path.join(app_dir, "conf.yml"), "w") as f:
            f.write("{}\n")

    rows = list_apps(root)
    names = [r["name"] for r in rows]
    assert "myapp" in names
    assert "vmn-registry" not in names


# ---------------------------------------------------------------------------
# vmn-registry hidden from UI app listing (S3)
# ---------------------------------------------------------------------------


def test_ui_list_apps_from_storage_ignores_registry():
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        # Seed two apps in S3: a real one and the reserved one
        s3 = boto3.client("s3")
        for app_key in ("myapp", "vmn-registry"):
            s3.put_object(
                Bucket=BUCKET,
                Key=f"{PREFIX}/{app_key}/0.0.1/metadata.yml",
                Body=b"verstr: '0.0.1'\n",
            )
        storage = S3SnapshotStorage(BUCKET, prefix=PREFIX)
        rows = list_apps_from_storage(storage)
    names = [r["name"] for r in rows]
    assert "myapp" in names
    assert "vmn-registry" not in names
    # tag_name_to_app_name converts "-" → "/"; ensure neither form appears
    assert "vmn/registry" not in names
