"""Every built-in backend passes the conformance kit a plugin author runs:
local (a tmp dir), S3 (moto), GCS and Azure Blob (fakes of their SDK
clients)."""
import itertools

import boto3
import pytest
from moto import mock_aws

from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions
from vmn_exp.storage import conformance


def _local(tmp_path):
    from vmn_exp.storage.local import LocalSnapshotStorage

    fresh = itertools.count()
    return lambda: LocalSnapshotStorage(str(tmp_path / f"store{next(fresh)}"), area="runs")


def _s3(tmp_path):
    from vmn_exp.storage.s3 import S3SnapshotStorage

    fresh = itertools.count()
    return lambda: S3SnapshotStorage("bkt", prefix=f"p{next(fresh)}")


def _gs(tmp_path):
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    return lambda: GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())


def _az(tmp_path):
    from vmn_exp.storage.azure import AzureSnapshotStorage

    return lambda: AzureSnapshotStorage(
        "bkt", prefix="p", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


@pytest.fixture
def aws(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="bkt")
        yield


@pytest.mark.parametrize("make", [_local, _s3, _gs, _az], ids=["local", "s3", "gs", "az"])
def test_builtin_store_passes_the_kit(make, tmp_path, aws):
    results = conformance.check_store(make(tmp_path))

    assert [(name, error) for name, error in results if error is not None] == []
