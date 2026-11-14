"""``open_record_stores(uri, options, s3_client_factory, local_store_at_root)``:
the records, code and runs stores of a ``file://``/directory or ``s3://`` URI."""
import os

import pytest

from s3_fakes import FakeS3Client
from version_stamp.snapshot.local_store import LocalRecordStore
from version_stamp.store.open import UnsupportedScheme, open_record_stores


class FakeFactory:
    def __init__(self):
        self.client = FakeS3Client()
        self.endpoints = []

    def __call__(self, endpoint_url):
        self.endpoints.append(endpoint_url)
        return self.client


def _open(uri, options=None, factory=None):
    return open_record_stores(uri, options, factory or FakeFactory(), LocalRecordStore.at_root)


def test_s3_uri_opens_three_areas_on_one_client():
    factory = FakeFactory()
    records, code, runs = _open("s3://b/p", factory=factory)
    assert (records.prefix, code.prefix, runs.prefix) == ("p/snapshots", "p/code", "p/runs")
    assert records._s3 is code._s3 is runs._s3 is factory.client
    assert factory.endpoints == [None]
    assert records.code_store is code and runs.code_store is code


def test_s3_records_land_under_the_prefix():
    factory = FakeFactory()
    records, _, _ = _open("s3://b/p", factory=factory)
    records.save("root/svc", "v1", {"verstr": "v1"}, {})
    assert factory.client.keys("b") == ["p/snapshots/root-svc/v1/metadata.yml"]


def test_s3_without_a_path_uses_the_default_root():
    records, _, _ = _open("s3://b")
    assert records.prefix == "vmn/snapshots"


def test_endpoint_url_from_the_uri_query():
    factory = FakeFactory()
    records, _, _ = _open("s3://b/p?endpoint_url=http://minio:9000", factory=factory)
    assert factory.endpoints == ["http://minio:9000"]
    assert records.endpoint_url == "http://minio:9000"


def test_endpoint_url_from_the_resolved_options():
    factory = FakeFactory()
    _open("s3://b/p", {"s3": {"endpoint_url": "http://minio:9000"}}, factory)
    assert factory.endpoints == ["http://minio:9000"]


def test_file_uri_opens_directory_stores(tmp_path):
    records, code, runs = _open(f"file://{tmp_path}")
    assert (records.root, records.area, code.area, runs.area) == (
        str(tmp_path), "snapshots", "code", "runs")
    assert records.code_store is code and runs.code_store is code
    records.save("app", "v1", {"verstr": "v1"}, {})
    assert os.path.isfile(tmp_path / "snapshots" / "app" / "v1" / "metadata.yml")


def test_a_bare_path_is_a_directory_store(tmp_path):
    records, _, _ = _open(str(tmp_path / "shared"))
    assert records.root == str(tmp_path / "shared")


def test_a_directory_store_builds_no_s3_client(tmp_path):
    factory = FakeFactory()
    _open(str(tmp_path), factory=factory)
    assert factory.endpoints == []


@pytest.mark.parametrize("uri,scheme", [("gs://b/p", "gs"), ("az://c/p", "az")])
def test_other_schemes_are_unsupported(uri, scheme):
    with pytest.raises(UnsupportedScheme) as raised:
        _open(uri)
    assert raised.value.scheme == scheme
