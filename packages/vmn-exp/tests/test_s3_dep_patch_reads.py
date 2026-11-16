"""The SDK's S3 ``load_record`` reads a record's dep patches through core's
``version_stamp.store.s3_reads.read_record``: only a missing deps prefix or
patch object means "no dep patches"; a failed dep read raises."""
import pytest
from s3_helpers import mocked_bucket, s3_storage

from botocore.exceptions import ClientError, EndpointConnectionError

APP = "my_app"


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


def test_a_record_with_deps_loads_its_dep_patches(s3):
    deps = {"lib": {"local_commits": "x"}, "other": {"working_tree": "w"}}
    s3.save(APP, "0.0.1", {"verstr": "0.0.1"}, {"working_tree": "d", "deps": deps})

    _, patches = s3.load_record(APP, "0.0.1")

    assert patches == {"working_tree": "d", "deps": deps}


def test_a_record_without_a_deps_prefix_loads_no_dep_patches(s3):
    s3.save(APP, "0.0.1", {"verstr": "0.0.1"}, {"working_tree": "d"})

    _, patches = s3.load_record(APP, "0.0.1")

    assert patches == {"working_tree": "d"}


def _failing_on(s3, monkeypatch, op, part, error):
    real = getattr(s3._s3, op)

    def call(**kwargs):
        if part in (kwargs.get("Key") or kwargs.get("Prefix") or ""):
            raise error
        return real(**kwargs)

    monkeypatch.setattr(s3._s3, op, call)


EXPIRED = ClientError({"Error": {"Code": "ExpiredToken"}}, "GetObject")


@pytest.mark.parametrize("error", [EXPIRED, EndpointConnectionError(endpoint_url="http://s3")],
                         ids=["credentials", "connection"])
def test_a_failed_dep_patch_get_raises(s3, monkeypatch, error):
    s3.save(APP, "0.0.1", {"verstr": "0.0.1"},
            {"working_tree": "d", "deps": {"lib": {"local_commits": "x"}}})
    _failing_on(s3, monkeypatch, "get_object", "/deps/", error)

    with pytest.raises(type(error)):
        s3.load_record(APP, "0.0.1")


def test_a_failed_deps_listing_raises(s3, monkeypatch):
    s3.save(APP, "0.0.1", {"verstr": "0.0.1"},
            {"working_tree": "d", "deps": {"lib": {"local_commits": "x"}}})
    _failing_on(s3, monkeypatch, "list_objects_v2", "/deps/",
                ClientError({"Error": {"Code": "AccessDenied"}}, "ListObjectsV2"))

    with pytest.raises(ClientError):
        s3.load_record(APP, "0.0.1")
