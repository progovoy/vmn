"""One path-component rule, enforced where storage joins paths."""
import os

import boto3
import pytest
from moto import mock_aws

from version_stamp.cli.snapshot import LocalSnapshotStorage, S3SnapshotStorage
from version_stamp.cli.snapshot_storage_files import valid_artifact_name
from version_stamp.core.utils import parse_record_metadata, valid_path_component
from version_stamp.ui.security import safe_segment

GOOD = ["0.0.1-dev.abc.def", "1.0.0+build.1", "model.pt", "a.b", "r2"]
BAD = ["", ".", "..", "../x", "a/b", "a\\b", "a..b", "x\0y"]


@pytest.mark.parametrize("name", GOOD)
def test_valid_components_pass_every_validator(name):
    assert valid_path_component(name)
    assert valid_artifact_name(name)
    assert safe_segment(name)


@pytest.mark.parametrize("name", BAD)
def test_invalid_components_fail_every_validator(name):
    assert not valid_path_component(name)
    assert not valid_artifact_name(name)
    assert not safe_segment(name)


def test_safe_segment_still_accepts_an_absent_value():
    assert safe_segment(None)


@pytest.fixture
def local(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


@pytest.mark.parametrize("verstr", ["../escape", "a/b", ".."])
def test_local_storage_refuses_a_verstr_that_is_not_one_component(local, verstr):
    with pytest.raises(ValueError):
        local.load("app", verstr)
    with pytest.raises(ValueError):
        local.save("app", verstr, {"verstr": verstr}, {})
    assert local.exists("app", verstr) is False


@pytest.mark.parametrize("app", ["../other", "a//b", "a/./b", "/abs", "a\\b"])
def test_local_storage_refuses_an_app_name_that_walks(local, app):
    with pytest.raises(ValueError):
        local.list_snapshots(app)


def test_nested_root_apps_are_still_fine(local):
    local.save("root/svc", "0.0.1", {"verstr": "0.0.1", "timestamp": "t"}, {})
    assert [m["verstr"] for m in local.list_snapshots("root/svc")] == ["0.0.1"]


def test_s3_storage_refuses_a_verstr_that_is_not_one_component():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        storage = S3SnapshotStorage("vmn-bucket", prefix="exp")
        with pytest.raises(ValueError):
            storage.load_file("app", "../x", "metadata.yml")
        assert storage.exists("app", "a/b") is False


# ---------------------------------------------------------------------------
# one metadata rule
# ---------------------------------------------------------------------------


def test_parse_record_metadata_keeps_records_only():
    assert parse_record_metadata(b"verstr: v1\nnote: n\n") == {"verstr": "v1", "note": "n"}
    assert parse_record_metadata(b"version: legacy\n") is None  # verinfo, not a record
    assert parse_record_metadata(b"[1, 2]") is None
    assert parse_record_metadata(b": : bad yaml: [") is None
    assert parse_record_metadata(None) is None


def test_storage_load_metadata_reads_metadata_alone(local):
    local.save("app", "v1", {"verstr": "v1", "timestamp": "t"}, {"untracked_files": b"x"})
    assert local.load_metadata("app", "v1") == {"verstr": "v1", "timestamp": "t"}
    assert local.load_metadata("app", "missing") is None
