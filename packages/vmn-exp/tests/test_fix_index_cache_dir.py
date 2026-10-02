"""Tests for the S3 experiment index cache-dir logic (E1)."""
import os
import stat

import pytest

from vmn_exp.storage.host_dirs import index_cache_path, index_cache_root


def s3_index_cache_path(endpoint_url, bucket, prefix, app_name):
    return index_cache_path(("s3", endpoint_url, bucket, prefix), app_name)


# ---------------------------------------------------------------------------
# index_cache_root
# ---------------------------------------------------------------------------


def test_env_override_is_used(monkeypatch, tmp_path):
    custom = str(tmp_path / "mycache")
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", custom)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert index_cache_root() == custom


def test_xdg_fallback_used_when_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv("VMN_INDEX_CACHE_DIR", raising=False)
    monkeypatch.delenv("VMN_EXP_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    root = index_cache_root()
    assert root == str(tmp_path / "xdg" / "vmn-exp")


def test_none_value_disables(monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", "none")
    assert index_cache_root() is None


def test_none_case_insensitive(monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", "NONE")
    assert index_cache_root() is None


# ---------------------------------------------------------------------------
# s3_index_cache_path
# ---------------------------------------------------------------------------


def test_distinct_endpoint_bucket_prefix_give_distinct_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path))
    app = "myapp"
    p1 = s3_index_cache_path(None, "bucket-a", "prefix", app)
    p2 = s3_index_cache_path(None, "bucket-b", "prefix", app)
    p3 = s3_index_cache_path(None, "bucket-a", "other-prefix", app)
    p4 = s3_index_cache_path("https://minio.local", "bucket-a", "prefix", app)
    assert len({p1, p2, p3, p4}) == 4, "Every distinct (endpoint,bucket,prefix) must map to a unique path"


def test_dotdot_in_prefix_stays_under_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path))
    path = s3_index_cache_path(None, "mybucket", "../../evil", "app")
    assert path is not None
    # The resulting path must be under tmp_path
    assert os.path.commonpath([str(tmp_path), path]) == str(tmp_path)


def test_dotdot_in_app_name_stays_under_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path))
    path = s3_index_cache_path(None, "mybucket", "prefix", "../../etc/passwd")
    assert path is not None
    assert os.path.commonpath([str(tmp_path), path]) == str(tmp_path)


def test_none_disables_returns_none(monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", "none")
    result = s3_index_cache_path(None, "bucket", "prefix", "app")
    assert result is None


def test_unwritable_root_returns_none(monkeypatch, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    # Remove write permission from root dir
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(locked))
    try:
        result = s3_index_cache_path(None, "bucket", "prefix", "app")
        assert result is None
    finally:
        locked.chmod(stat.S_IRWXU)  # restore so cleanup works


def test_path_ends_with_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path))
    path = s3_index_cache_path(None, "mybucket", "prefix", "myapp")
    assert path is not None
    assert path.endswith(".sqlite")


def test_path_is_under_index_subdir(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path))
    path = s3_index_cache_path(None, "mybucket", "prefix", "myapp")
    assert path is not None
    rel = os.path.relpath(path, str(tmp_path))
    assert rel.startswith("index" + os.sep)


# ---------------------------------------------------------------------------
# Buffered storage delegates to its S3 remote
# ---------------------------------------------------------------------------


def test_buffered_delegates_to_remote_index_cache_path(monkeypatch, tmp_path):
    """BufferedRemoteStorage.index_cache_path must delegate to its S3 remote."""
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path))

    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket="test-bucket")
        from vmn_exp.storage.buffered import BufferedRemoteStorage
        from vmn_exp.storage.s3 import S3SnapshotStorage

        remote = S3SnapshotStorage("test-bucket", prefix="exps")
        buf = BufferedRemoteStorage(remote)

        s3_path = remote.index_cache_path("myapp")
        buf_path = buf.index_cache_path("myapp")
        assert s3_path is not None
        assert buf_path == s3_path
