"""``download_model`` of a version at an absolute ``artifact_path``: a local
path (or ``file://`` URI) is read from disk, an ``s3://``/``gs://``/``az://``
URI through its storage backend — not looked up in the run's record ("not
found in storage"); a scheme whose extra is missing says which to install."""
import sys

import boto3
import pytest
from s3_helpers import BUCKET, mocked_bucket

from vmn_exp.sdk.models import download_model, register_model
from vmn_exp.storage.local import LocalSnapshotStorage


def _registered(tmp_path, path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    register_model("clf", run="0.0.1-dev.aaa", app_name="trainer", artifact_path=path,
                   storage=storage)
    return storage


def _local_model(tmp_path, data=b"weights"):
    path = tmp_path / "models" / "clf.pt"
    path.parent.mkdir()
    path.write_bytes(data)
    return str(path)


def test_an_absolute_local_path_is_read_from_disk(tmp_path):
    path = _local_model(tmp_path)
    storage = _registered(tmp_path, path)
    assert download_model("clf@1", storage=storage, record=False) == path
    copied = download_model("clf@1", dst=str(tmp_path / "out"), storage=storage, record=False)
    assert open(copied, "rb").read() == b"weights"


def test_a_file_uri_is_read_from_disk(tmp_path):
    path = _local_model(tmp_path)
    storage = _registered(tmp_path, f"file://{path}")
    assert download_model("clf@1", storage=storage, record=False) == path


def test_a_missing_absolute_path_names_it(tmp_path):
    storage = _registered(tmp_path, "/no/such/clf.pt")
    with pytest.raises(FileNotFoundError, match="'/no/such/clf.pt' not found") as err:
        download_model("clf@1", storage=storage, record=False)
    assert "in storage" not in str(err.value)


def test_an_s3_uri_downloads_through_the_s3_backend(tmp_path, monkeypatch):
    with mocked_bucket(monkeypatch):
        boto3.client("s3").put_object(Bucket=BUCKET, Key="models/clf.pt", Body=b"remote")
        storage = _registered(tmp_path, f"s3://{BUCKET}/models/clf.pt")
        local = download_model("clf@1", storage=storage, record=False)
        assert open(local, "rb").read() == b"remote"
        with pytest.raises(FileNotFoundError, match=f"s3://{BUCKET}/models/gone.pt"):
            download_model("clf@1", storage=_registered(tmp_path / "b", f"s3://{BUCKET}/models/gone.pt"),
                           record=False)


def test_a_scheme_without_its_extra_says_which_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "google.cloud.storage", None)
    storage = _registered(tmp_path, "gs://bucket/models/clf.pt")
    with pytest.raises(ImportError, match=r"pip install 'vmn-exp-sdk\[gcs\]'"):
        download_model("clf@1", storage=storage, record=False)
