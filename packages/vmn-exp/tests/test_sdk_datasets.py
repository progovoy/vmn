"""Datasets in the registry: reference and copied modes (plan 06)."""
import hashlib
import os

import boto3
import pytest
from moto import mock_aws

from test_sdk_usage import FakeRun, _producer

from vmn_exp.registry.digest import local_digest
from vmn_exp.registry.log import read_uses
from vmn_exp.registry.store import list_versions
from vmn_exp.registry.view import models_for_run, registered_runs
from vmn_exp.sdk.datasets import get_dataset_version, register_dataset
from vmn_exp.sdk.models import download_model, register_model
from vmn_exp.sdk.usage import use_dataset
from vmn_exp.storage.local import LocalSnapshotStorage

BUCKET = "vmn-test-bucket"


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), subdir="experiments")


def _file(tmp_path, name="train.csv", data=b"a,b\n1,2\n"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_register_dataset_reference_local_file_computes_digest(tmp_path):
    storage = _storage(tmp_path)
    path = _file(tmp_path)
    meta = register_dataset("train", path, storage=storage)
    assert meta["n"] == 1
    assert meta["uri"] == os.path.abspath(path)
    assert meta["digest"] == "sha256:" + hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    assert (meta["size"], meta["files"]) == (8, 1)
    assert "run_ref" not in meta


def test_register_dataset_dir_manifest(tmp_path):
    storage = _storage(tmp_path)
    root = tmp_path / "ds"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"A")
    (root / "sub" / "b.txt").write_bytes(b"BB")
    meta = register_dataset("images", str(root), storage=storage)
    assert meta["digest"] == local_digest(str(root))["digest"]
    assert (meta["size"], meta["files"]) == (3, 2)


def test_register_dataset_dedupes_same_digest_returns_existing_n(tmp_path):
    storage = _storage(tmp_path)
    path = _file(tmp_path)
    assert register_dataset("train", path, storage=storage)["n"] == 1
    assert register_dataset("train", path, storage=storage, alias="prod")["n"] == 1
    assert list_versions(storage, "train") == [1]
    assert get_dataset_version("train@prod", storage=storage)["n"] == 1
    assert register_dataset("train", path, storage=storage, dedupe=False)["n"] == 2
    _file(tmp_path, data=b"changed")
    assert register_dataset("train", path, storage=storage)["n"] == 3


def test_register_dataset_copied_mode_points_at_run_artifact(tmp_path):
    storage = _storage(tmp_path)
    digest = _producer(storage, app="prep", verstr="0.1", path="data/train.parquet", data=b"pq")
    meta = register_dataset("train", run="0.1", app_name="prep",
                            artifact_path="data/train.parquet", storage=storage)
    assert meta["run_ref"] == {"app": "prep", "verstr": "0.1"}
    assert meta["artifact_path"] == "data/train.parquet"
    assert meta["digest"] == digest
    assert ("prep", "0.1") in registered_runs(storage)
    assert [m["kind"] for m in models_for_run(storage, "prep", "0.1")] == ["dataset"]


def test_register_dataset_requires_exactly_one_mode(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError):
        register_dataset("train", storage=storage)
    with pytest.raises(ValueError):
        register_dataset("train", _file(tmp_path), run="0.1", app_name="prep",
                         artifact_path="x", storage=storage)


def test_register_dataset_refuses_a_model_name(tmp_path):
    storage = _storage(tmp_path)
    _producer(storage, app="trainer", verstr="0.1")
    register_model("resnet", run="0.1", app_name="trainer", artifact_path="model.pkl",
                   storage=storage)
    with pytest.raises(ValueError, match="model"):
        register_dataset("resnet", _file(tmp_path), storage=storage)
    with pytest.raises(ValueError, match="model"):
        get_dataset_version("resnet", storage=storage)


def test_use_reference_dataset_logs_registry_uri(tmp_path):
    storage = _storage(tmp_path)
    meta = register_dataset("train", _file(tmp_path), storage=storage)
    run = FakeRun(storage, "trainer", "1.0.0")
    assert use_dataset("train", run=run, storage=storage)["n"] == 1
    assert run.inputs() == {
        "train@1": {"uri": "vmn-registry://train@1", "digest": meta["digest"], "kind": "dataset"}
    }
    assert [(u["app"], u["verstr"]) for u in read_uses(storage, "train")[1]] == [
        ("trainer", "1.0.0")
    ]


def test_download_model_on_reference_dataset_raises_value_error(tmp_path):
    storage = _storage(tmp_path)
    register_dataset("train", "s3://data/train/", digest="sha256:ab", storage=storage)
    with pytest.raises(ValueError, match="reference"):
        download_model("train", storage=storage)


class _RecordingRun:
    app_name, id = "trainer", "1.0.0"

    def __init__(self):
        self.inputs = []

    def log_input(self, uri, name=None, digest=None, kind=None):
        self.inputs.append((uri, name, digest, kind))


def test_s3_reference_dataset_round_trip(monkeypatch):
    for key, value in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                           AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        from vmn_exp.storage.s3 import S3SnapshotStorage

        storage = S3SnapshotStorage(BUCKET, prefix="vmn-experiments")
        register_dataset("imagenet", "s3://data/imagenet/", digest="sha256:ab", storage=storage)
        meta = get_dataset_version("imagenet@1", storage=storage)
        assert (meta["uri"], meta["digest"]) == ("s3://data/imagenet/", "sha256:ab")
        assert register_dataset("imagenet", "s3://data/imagenet/", digest="sha256:ab",
                                storage=storage)["n"] == 1

        run = _RecordingRun()
        use_dataset("imagenet", run=run, storage=storage)
        assert run.inputs == [
            ("vmn-registry://imagenet@1", "imagenet@1", "sha256:ab", "dataset")
        ]
        assert [u["verstr"] for u in read_uses(storage, "imagenet")[1]] == ["1.0.0"]
