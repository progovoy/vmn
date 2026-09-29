"""Request economy of the GCS/Azure adapters: a GCS read is one download
(no metadata GET first), an Azure full listing reads each blob once (Azure
has no server-side StartAfter), and a missing boto3 names the extra."""
import builtins

import pytest

from object_store_fakes import FakeContainerClient, FakeGCSBucket, FakeGCSClient, MatchConditions

APP = "trainer"
V1 = "1.2.0-dev.abc1234.0000001"
V2 = "1.2.0-dev.abc1234.0000002"


class _NoStatBucket(FakeGCSBucket):
    def get_blob(self, name):
        raise AssertionError("a read must not fetch the blob's metadata first")


class _NoStatClient(FakeGCSClient):
    def bucket(self, name):
        return self.buckets.setdefault(name, _NoStatBucket(name))


def test_gcs_read_is_a_single_download():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    client = FakeGCSClient()
    GCSSnapshotStorage("bkt", prefix="p", client=client).save(
        APP, V1, {"verstr": V1, "app": APP}, {}
    )
    reader_client = _NoStatClient()
    reader_client.buckets["bkt"] = _NoStatBucket("bkt")
    reader_client.buckets["bkt"].objects = client.bucket("bkt").objects
    reader = GCSSnapshotStorage("bkt", prefix="p", client=reader_client)

    assert reader.load_metadata(APP, V1)["verstr"] == V1
    assert reader.load_file(APP, V1, "missing.txt") is None
    assert reader.update_metadata(APP, V1, {"note": "cas"})  # ETag from the download
    assert reader.load_metadata(APP, V1)["note"] == "cas"


class _CountingContainer(FakeContainerClient):
    yielded = 0

    def list_blobs(self, name_starts_with=None):
        for item in super().list_blobs(name_starts_with):
            type(self).yielded += 1
            yield item


def test_azure_full_listing_reads_each_blob_once():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    container = _CountingContainer("bkt")
    storage = AzureSnapshotStorage("bkt", prefix="p", container=container,
                                   if_not_modified=MatchConditions.IfNotModified)
    for verstr in (V1, V2):
        storage.save(APP, verstr, {"verstr": verstr, "app": APP}, {})
        for i in range(1500):  # a subtree bigger than a listing page
            storage._put(f"p/{APP}/{verstr}/artifacts/ckpt{i:05d}", b"x")
    _CountingContainer.yielded = 0

    assert set(storage.list_files(APP)) == {V1, V2}
    assert _CountingContainer.yielded <= len(container.objects)


def test_missing_boto3_names_the_s3_extra(monkeypatch):
    from vmn_exp.storage.registry import missing_extra
    from vmn_exp.storage.s3_base import boto3_client

    real_import = builtins.__import__

    def no_boto3(name, *args, **kwargs):
        if name == "boto3":
            raise ImportError("no boto3")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_boto3)
    with pytest.raises(ImportError) as err:
        boto3_client()
    assert str(err.value) == str(missing_extra("boto3", "s3"))
