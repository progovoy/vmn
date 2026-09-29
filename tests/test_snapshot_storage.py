"""Snapshot storage backends: S3 round-trips, cached-storage error
propagation and the collision-free dev verstr a new record claims."""
from unittest.mock import MagicMock, patch as mock_patch

import boto3
import pytest
import yaml
from moto import mock_aws

from vmn_exp.snapshot import LocalSnapshotStorage, _unique_snapshot_verstr
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.s3 import S3SnapshotStorage
from version_stamp.core.logging import init_stamp_logger
from version_stamp.core.version_math import deserialize_vmn_version


@mock_aws
def test_s3_snapshot_save():
    """Test S3 backend save — full round-trip via moto."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    storage = S3SnapshotStorage("test-bucket", prefix="test-prefix")

    metadata = {"verstr": "1.0.0-dev.abc1234.def5678", "base_version": "1.0.0"}
    patches = {"working_tree": "diff --git a/f.txt b/f.txt\n+hello\n"}

    storage.save("my_app", "1.0.0-dev.abc1234.def5678", metadata, patches)

    # Verify objects were actually written
    meta_resp = s3.get_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/metadata.yml",
    )
    loaded = yaml.safe_load(meta_resp["Body"].read().decode("utf-8"))
    assert loaded["verstr"] == "1.0.0-dev.abc1234.def5678"

    patch_resp = s3.get_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/working_tree.patch",
    )
    assert b"+hello" in patch_resp["Body"].read()


@mock_aws
def test_s3_snapshot_load():
    """Test S3 backend load — full round-trip via moto."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # Seed data
    metadata = {"verstr": "1.0.0-dev.abc1234.def5678", "base_version": "1.0.0"}
    s3.put_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/metadata.yml",
        Body=yaml.dump(metadata).encode("utf-8"),
    )
    s3.put_object(
        Bucket="test-bucket",
        Key="test-prefix/my_app/1.0.0-dev.abc1234.def5678/working_tree.patch",
        Body=b"diff content",
    )

    storage = S3SnapshotStorage("test-bucket", prefix="test-prefix")

    loaded_meta, loaded_patches = storage.load("my_app", "1.0.0-dev.abc1234.def5678")
    assert loaded_meta["verstr"] == "1.0.0-dev.abc1234.def5678"
    assert loaded_patches["working_tree"] == "diff content"


@mock_aws
def test_s3_snapshot_load_not_found():
    """Test S3 backend returns None for missing snapshot."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    storage = S3SnapshotStorage("test-bucket")

    meta, patches = storage.load("my_app", "nonexistent")
    assert meta is None
    assert patches is None


@mock_aws
def test_s3_snapshot_list():
    """Test S3 backend list_snapshots — full round-trip via moto."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    storage = S3SnapshotStorage("test-bucket")

    # Save two snapshots
    meta1 = {"verstr": "1.0.0-dev.aaa.bbb", "timestamp": "2025-01-01T00:00:00Z"}
    meta2 = {"verstr": "1.0.0-dev.ccc.ddd", "timestamp": "2025-01-02T00:00:00Z"}
    storage.save("my_app", "1.0.0-dev.aaa.bbb", meta1, {})
    storage.save("my_app", "1.0.0-dev.ccc.ddd", meta2, {})

    snapshots = storage.list_snapshots("my_app")
    assert len(snapshots) == 2
    assert snapshots[0]["verstr"] == "1.0.0-dev.aaa.bbb"
    assert snapshots[1]["verstr"] == "1.0.0-dev.ccc.ddd"


def test_s3_snapshot_endpoint_url():
    """Test S3 backend passes endpoint_url to boto3."""
    with mock_patch("boto3.client") as mock_boto:
        S3SnapshotStorage("test-bucket", endpoint_url="http://localhost:9000")
        mock_boto.assert_called_once_with("s3", endpoint_url="http://localhost:9000")


@pytest.fixture
def cached_storage_with_mock_remote(tmp_path):
    """Provide a CachedSnapshotStorage wired to a real local and a mock remote."""
    try:
        init_stamp_logger()
    except Exception:
        pass
    local = LocalSnapshotStorage(str(tmp_path))
    remote = MagicMock()
    cached = CachedSnapshotStorage(local, remote)
    return local, remote, cached


_TEST_VERSTR = "1.0.0-dev.abc1234.def5678"
_TEST_APP = "test_app"
_TEST_META = {"verstr": _TEST_VERSTR, "app_name": "test"}


def test_cached_storage_raises_on_remote_save_failure(cached_storage_with_mock_remote):
    """CachedSnapshotStorage must propagate write errors from remote storage."""
    _, remote, cached = cached_storage_with_mock_remote
    remote.save.side_effect = Exception("S3 bucket not found")

    with pytest.raises(Exception, match="S3 bucket not found"):
        cached.save(_TEST_APP, _TEST_VERSTR, _TEST_META, {"working_tree": "patch"})


def test_cached_storage_raises_on_remote_delete_failure(
    cached_storage_with_mock_remote,
):
    """CachedSnapshotStorage must propagate delete errors from remote storage."""
    local, remote, cached = cached_storage_with_mock_remote
    remote.delete.side_effect = Exception("S3 access denied")

    local.save(_TEST_APP, _TEST_VERSTR, _TEST_META, {"working_tree": "data"})

    with pytest.raises(Exception, match="S3 access denied"):
        cached.delete(_TEST_APP, _TEST_VERSTR)


def test_cached_storage_raises_on_remote_update_note_failure(
    cached_storage_with_mock_remote,
):
    """CachedSnapshotStorage must propagate update_note errors from remote storage."""
    local, remote, cached = cached_storage_with_mock_remote
    remote.update_note.side_effect = Exception("S3 timeout")

    local.save(_TEST_APP, _TEST_VERSTR, _TEST_META, {})

    with pytest.raises(Exception, match="S3 timeout"):
        cached.update_note(_TEST_APP, _TEST_VERSTR, "my note")


def test_cached_storage_raises_on_remote_save_file_failure(
    cached_storage_with_mock_remote,
):
    """CachedSnapshotStorage must propagate save_file errors from remote storage."""
    _, remote, cached = cached_storage_with_mock_remote
    remote.save_file.side_effect = Exception("S3 write failed")

    with pytest.raises(Exception, match="S3 write failed"):
        cached.save_file(_TEST_APP, _TEST_VERSTR, "out.txt", b"data")


def test_cached_storage_raises_on_remote_save_artifact_file_failure(
    cached_storage_with_mock_remote, tmp_path
):
    """CachedSnapshotStorage must propagate save_artifact_file errors from remote."""
    _, remote, cached = cached_storage_with_mock_remote
    remote.save_artifact_file.side_effect = Exception("S3 permission denied")

    artifact_path = str(tmp_path / "artifact.bin")
    with open(artifact_path, "wb") as f:
        f.write(b"artifact data")

    with pytest.raises(Exception, match="S3 permission denied"):
        cached.save_artifact_file(_TEST_APP, _TEST_VERSTR, artifact_path)


# ---------------------------------------------------------------------------
# verstr identity: a new record never overwrites a different one
# ---------------------------------------------------------------------------

_COMMIT = "c" * 40


def _claim(storage, diff_hash):
    return _unique_snapshot_verstr(storage, _TEST_APP, "0.0.1", _COMMIT, diff_hash)


def _save(storage, verstr, **meta):
    storage.save(_TEST_APP, verstr, {"verstr": verstr, **meta}, {})


def test_colliding_diff_hash_extends_instead_of_overwriting(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    first, second = "abcdef1" + "0" * 57, "abcdef1" + "1" * 57
    taken = _claim(storage, first)
    _save(storage, taken, diff_hash=first)

    assert taken == "0.0.1-dev.ccccccc.abcdef1"
    assert _claim(storage, second) == "0.0.1-dev.ccccccc.abcdef111111"


def test_same_diff_hash_stays_idempotent(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    same = "abcdef1" + "2" * 57
    taken = _claim(storage, same)
    _save(storage, taken, diff_hash=same)

    assert _claim(storage, same) == taken


def test_legacy_record_without_diff_hash_is_not_overwritten(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    _save(storage, "0.0.1-dev.ccccccc.abcdef1", note="legacy")

    assert _claim(storage, "abcdef1" + "3" * 57) == "0.0.1-dev.ccccccc.abcdef133333"


def test_extended_dev_verstr_parses():
    props = deserialize_vmn_version("0.0.1-dev.abcdef1.abcdef111111")
    assert props.dev_commit == "abcdef1"
    assert props.dev_diff_hash == "abcdef111111"

    run = deserialize_vmn_version("0.0.1-dev.abcdef1.abcdef111111.r3")
    assert run.dev_diff_hash == "abcdef111111"
    assert run.dev_run == 3
