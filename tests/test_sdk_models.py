"""Tests for C8: SDK model registry helpers in vmn_exp/sdk/models.py.

Coverage:
- register_model from a finished run returns v1 with run_ref + artifact_uri
- alias + get_model_version by alias / version number / latest
- download_model returns a path with the artifact contents (local storage)
- S3 via moto (register + download)
- Run.register_model convenience method inside start_run
"""
import os
import tempfile

import boto3
import pytest
from moto import mock_aws

from helpers import _bootstrap, _storage

from vmn_exp.sdk import start_run
from vmn_exp.sdk.models import (
    download_model,
    get_model_version,
    list_models,
    register_model,
    remove_alias,
    set_alias,
)

BUCKET = "vmn-test-bucket"
PREFIX = "vmn-experiments"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def _aws_env(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x",
        AWS_SECRET_ACCESS_KEY="x",
        AWS_DEFAULT_REGION="us-east-1",
    ).items():
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------------------
# Test 1: register from a finished run → v1 with run_ref + artifact_uri
# ---------------------------------------------------------------------------


def test_register_from_finished_run_returns_v1_with_run_ref_and_artifact_uri(app_layout):
    _bootstrap(app_layout)
    storage = _storage(app_layout)

    # Create a temp artifact file
    artifact_file = tempfile.NamedTemporaryFile(
        suffix=".pkl", delete=False, mode="w"
    )
    artifact_file.write("weights")
    artifact_file.close()

    try:
        with start_run(app_layout.app_name) as run:
            run.log_artifact(artifact_file.name, name="model/weights.pkl")
            run_verstr = run.id
            run_app = run.app_name
    finally:
        os.unlink(artifact_file.name)

    meta = register_model(
        "resnet",
        run=run,
        artifact_path="model/weights.pkl",
        description="first model",
        storage=storage,
    )

    assert meta["n"] == 1
    assert isinstance(meta["run_ref"], dict)
    assert meta["run_ref"]["app"] == run_app
    assert meta["run_ref"]["verstr"] == run_verstr
    assert meta["artifact_path"] == "model/weights.pkl"
    assert meta.get("description") == "first model"

    # Second register → v2
    meta2 = register_model("resnet", run=run, storage=storage)
    assert meta2["n"] == 2

    # list_models sees the model
    models = list_models(storage=storage)
    assert "resnet" in models


# ---------------------------------------------------------------------------
# Test 2: alias + get_model_version by alias / number / latest
# ---------------------------------------------------------------------------


def test_alias_and_get_model_version(app_layout):
    _bootstrap(app_layout)
    storage = _storage(app_layout)

    with start_run(app_layout.app_name) as run:
        pass  # no artifact needed for alias tests

    # Register with an alias
    meta = register_model(
        "bert",
        run=run,
        alias="production",
        storage=storage,
    )
    assert meta["n"] == 1

    # get_model_version by alias
    by_alias = get_model_version("bert@production", storage=storage)
    assert by_alias["n"] == 1

    # get_model_version by number
    by_num = get_model_version("bert@1", storage=storage)
    assert by_num["n"] == 1

    # get_model_version by latest (bare model name)
    by_latest = get_model_version("bert", storage=storage)
    assert by_latest["n"] == 1

    # get_model_version by explicit @latest
    by_latest2 = get_model_version("bert@latest", storage=storage)
    assert by_latest2["n"] == 1

    # Move alias to a new version
    meta2 = register_model("bert", run=run, storage=storage)
    set_alias("bert", "production", 2, storage=storage)
    updated = get_model_version("bert@production", storage=storage)
    assert updated["n"] == 2

    # latest now returns v2
    assert get_model_version("bert@latest", storage=storage)["n"] == 2

    # Remove alias
    remove_alias("bert", "production", storage=storage)
    with pytest.raises(KeyError):
        get_model_version("bert@production", storage=storage)


# ---------------------------------------------------------------------------
# Test 3: download_model returns a path with the artifact contents (local)
# ---------------------------------------------------------------------------


def test_download_model_returns_path_with_artifact_contents_local(app_layout):
    _bootstrap(app_layout)
    storage = _storage(app_layout)

    artifact_file = tempfile.NamedTemporaryFile(
        suffix=".pkl", delete=False, mode="w"
    )
    artifact_file.write("model_data_v1")
    artifact_file.close()

    try:
        with start_run(app_layout.app_name) as run:
            run.log_artifact(artifact_file.name, name="weights.pkl")
    finally:
        os.unlink(artifact_file.name)

    register_model(
        "gpt",
        run=run,
        artifact_path="weights.pkl",
        storage=storage,
    )

    local_path = download_model("gpt@latest", storage=storage)
    assert os.path.exists(local_path), f"artifact path not found: {local_path}"
    with open(local_path) as f:
        assert f.read() == "model_data_v1"


# ---------------------------------------------------------------------------
# Test 4: S3 via moto — register + download
# ---------------------------------------------------------------------------


def test_download_model_s3(_aws_env):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)

        from vmn_exp.storage.s3 import S3SnapshotStorage
        storage = S3SnapshotStorage(BUCKET, prefix=PREFIX)

        # Write a fake artifact directly into the S3 run record
        content = b"s3_weights"
        run_app = "myapp"
        run_verstr = "0.0.1-s3.abc"
        key = f"{PREFIX}/{run_app}/{run_verstr}/artifacts/model.bin"
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=BUCKET, Key=key, Body=content
        )

        # Also create a fake metadata.yml so the record "exists"
        import yaml
        meta_key = f"{PREFIX}/{run_app}/{run_verstr}/metadata.yml"
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=BUCKET,
            Key=meta_key,
            Body=yaml.dump({"verstr": run_verstr, "app_name": run_app}).encode(),
        )

        run_ref = {"app": run_app, "verstr": run_verstr}
        from vmn_exp.registry.store import ensure_model, register_version
        ensure_model(storage, "vgg")
        register_version(
            storage, "vgg", run_ref=run_ref, artifact_path="model.bin"
        )

        path = download_model("vgg@latest", storage=storage)
        assert os.path.isfile(path)
        with open(path, "rb") as f:
            assert f.read() == content


# ---------------------------------------------------------------------------
# Test 5: Run.register_model convenience method
# ---------------------------------------------------------------------------


def test_run_register_model_inside_start_run(app_layout):
    _bootstrap(app_layout)
    storage = _storage(app_layout)

    artifact_file = tempfile.NamedTemporaryFile(
        suffix=".pkl", delete=False, mode="w"
    )
    artifact_file.write("run_register_test")
    artifact_file.close()

    try:
        with start_run(app_layout.app_name) as run:
            run.log_artifact(artifact_file.name, name="ckpt.pkl")
            meta = run.register_model(
                "efficientnet",
                artifact_path="ckpt.pkl",
                alias="staging",
                storage=storage,
            )
    finally:
        os.unlink(artifact_file.name)

    assert meta["n"] == 1
    assert meta["run_ref"]["verstr"] == run.id

    # Can resolve after the run is closed
    resolved = get_model_version("efficientnet@staging", storage=storage)
    assert resolved["n"] == 1
