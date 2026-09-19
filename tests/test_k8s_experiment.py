"""K8s-scale experiment tracking: per-writer JSONL logs, pod-unique verstr
allocation, snapshot-based creation, and git-free dispatch."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
import pytest
import yaml
from moto import mock_aws

from version_stamp.cli.snapshot import (
    CachedSnapshotStorage,
    LocalSnapshotStorage,
    S3SnapshotStorage,
)
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


@pytest.fixture
def exp_storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _save_exp(storage, app, verstr, ts="2025-01-01T00:00:00Z"):
    """Save minimal experiment metadata."""
    storage.save(app, verstr, {
        "verstr": verstr, "app_name": app, "timestamp": ts,
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }, {})


# =========================================================================
# A. Per-writer JSONL log files (LocalSnapshotStorage)
# =========================================================================

def test_append_log_creates_jsonl_file(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    entry = {"timestamp": "t1", "type": "metrics", "values": {"loss": 0.5}}
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", entry)

    snap_dir = exp_storage._snapshot_dir("app", "1.0.0-dev.aaa.bbb")
    log_path = os.path.join(snap_dir, "log.pod-1.jsonl")
    assert os.path.isfile(log_path)
    with open(log_path) as f:
        lines = f.read().strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "metrics"


def test_append_log_multiple_entries_same_writer(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    e1 = {"timestamp": "t1", "type": "metrics", "values": {"loss": 0.5}}
    e2 = {"timestamp": "t2", "type": "note", "text": "hello"}
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", e1)
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", e2)

    snap_dir = exp_storage._snapshot_dir("app", "1.0.0-dev.aaa.bbb")
    log_path = os.path.join(snap_dir, "log.pod-1.jsonl")
    with open(log_path) as f:
        lines = [l for l in f.read().strip().split("\n") if l.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "metrics"
    assert json.loads(lines[1])["type"] == "note"


def test_load_merged_log_single_writer(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    e1 = {"timestamp": "2025-01-01T00:00:00Z", "type": "create"}
    e2 = {"timestamp": "2025-01-01T00:01:00Z", "type": "metrics", "values": {"loss": 0.3}}
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", e1)
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", e2)

    merged = exp_storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 2
    assert merged[0]["type"] == "create"
    assert merged[1]["type"] == "metrics"


def test_load_merged_log_multiple_writers(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    e1 = {"timestamp": "2025-01-01T00:00:00Z", "type": "metrics", "values": {"loss": 0.5}}
    e2 = {"timestamp": "2025-01-01T00:00:01Z", "type": "metrics", "values": {"acc": 0.9}}
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", e1)
    exp_storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-2", e2)

    merged = exp_storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 2
    # Sorted by timestamp
    assert merged[0]["values"]["loss"] == 0.5
    assert merged[1]["values"]["acc"] == 0.9


def test_load_merged_log_backward_compat_legacy_log_yml(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    snap_dir = exp_storage._snapshot_dir("app", "1.0.0-dev.aaa.bbb")
    legacy_entries = [
        {"timestamp": "2025-01-01T00:00:00Z", "type": "create", "note": "legacy"},
    ]
    with open(os.path.join(snap_dir, "log.yml"), "w") as f:
        yaml.dump(legacy_entries, f)

    merged = exp_storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 1
    assert merged[0]["note"] == "legacy"


def test_load_merged_log_empty(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    merged = exp_storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert merged == []


def test_load_merged_log_ignores_malformed_jsonl_lines(exp_storage):
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    snap_dir = exp_storage._snapshot_dir("app", "1.0.0-dev.aaa.bbb")
    log_path = os.path.join(snap_dir, "log.pod-1.jsonl")
    with open(log_path, "w") as f:
        f.write(json.dumps({"timestamp": "t1", "type": "metrics"}) + "\n")
        f.write("NOT VALID JSON\n")

    merged = exp_storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 1
    assert merged[0]["type"] == "metrics"


# =========================================================================
# B. S3 JSONL log files (S3SnapshotStorage)
# =========================================================================

@mock_aws
def test_s3_append_log_entry():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    storage = S3SnapshotStorage("test-bucket", prefix="exp")
    _save_exp(storage, "app", "1.0.0-dev.aaa.bbb")

    entry = {"timestamp": "t1", "type": "metrics", "values": {"loss": 0.5}}
    storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "writer", entry)

    resp = s3.get_object(
        Bucket="test-bucket",
        Key="exp/app/1.0.0-dev.aaa.bbb/log.writer.jsonl",
    )
    content = resp["Body"].read().decode("utf-8")
    lines = [l for l in content.strip().split("\n") if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "metrics"


@mock_aws
def test_s3_append_log_entry_appends_to_existing():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    storage = S3SnapshotStorage("test-bucket", prefix="exp")
    _save_exp(storage, "app", "1.0.0-dev.aaa.bbb")

    e1 = {"timestamp": "t1", "type": "metrics", "values": {"loss": 0.5}}
    e2 = {"timestamp": "t2", "type": "note", "text": "hello"}
    storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "writer", e1)
    storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "writer", e2)

    resp = s3.get_object(
        Bucket="test-bucket",
        Key="exp/app/1.0.0-dev.aaa.bbb/log.writer.jsonl",
    )
    content = resp["Body"].read().decode("utf-8")
    lines = [l for l in content.strip().split("\n") if l.strip()]
    assert len(lines) == 2


@mock_aws
def test_s3_load_merged_log_reads_jsonl_files():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    storage = S3SnapshotStorage("test-bucket", prefix="exp")
    _save_exp(storage, "app", "1.0.0-dev.aaa.bbb")

    e1 = {"timestamp": "2025-01-01T00:00:00Z", "type": "create"}
    e2 = {"timestamp": "2025-01-01T00:01:00Z", "type": "metrics", "values": {"loss": 0.3}}
    storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", e1)
    storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-2", e2)

    merged = storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 2
    types = [e["type"] for e in merged]
    assert "create" in types
    assert "metrics" in types


@mock_aws
def test_s3_load_merged_log_with_legacy_log_yml():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    storage = S3SnapshotStorage("test-bucket", prefix="exp")
    _save_exp(storage, "app", "1.0.0-dev.aaa.bbb")

    # Write legacy log.yml
    legacy = [{"timestamp": "2025-01-01T00:00:00Z", "type": "create", "note": "legacy"}]
    storage.save_file("app", "1.0.0-dev.aaa.bbb", "log.yml",
                      yaml.dump(legacy, sort_keys=False))
    # Write per-writer JSONL
    e = {"timestamp": "2025-01-01T00:01:00Z", "type": "metrics", "values": {"loss": 0.5}}
    storage.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod", e)

    merged = storage.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 2
    types = [e["type"] for e in merged]
    assert "create" in types
    assert "metrics" in types


# =========================================================================
# C. CachedSnapshotStorage log methods
# =========================================================================

def test_cached_append_log_writes_local_only(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    remote = MagicMock()
    cached = CachedSnapshotStorage(local, remote)
    _save_exp(local, "app", "1.0.0-dev.aaa.bbb")

    entry = {"timestamp": "t1", "type": "metrics"}
    cached.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", entry)

    # Local has the entry
    merged = local.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 1
    # Remote was not called for append
    remote.append_log_entry.assert_not_called()


def test_cached_load_merged_log_local_first(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    remote = MagicMock()
    cached = CachedSnapshotStorage(local, remote)
    _save_exp(local, "app", "1.0.0-dev.aaa.bbb")

    entry = {"timestamp": "t1", "type": "create"}
    local.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", entry)

    merged = cached.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 1
    remote.load_merged_log.assert_not_called()


def test_cached_load_merged_log_falls_back_to_remote(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    remote = MagicMock()
    remote.load_merged_log.return_value = [
        {"timestamp": "t1", "type": "create", "note": "from remote"},
    ]
    cached = CachedSnapshotStorage(local, remote)
    _save_exp(local, "app", "1.0.0-dev.aaa.bbb")

    merged = cached.load_merged_log("app", "1.0.0-dev.aaa.bbb")
    assert len(merged) == 1
    assert merged[0]["note"] == "from remote"
    remote.load_merged_log.assert_called_once()


def test_cached_sync_log_to_remote(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    remote = MagicMock()
    cached = CachedSnapshotStorage(local, remote)
    _save_exp(local, "app", "1.0.0-dev.aaa.bbb")

    entry = {"timestamp": "t1", "type": "metrics"}
    cached.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", entry)
    cached.sync_log_to_remote("app", "1.0.0-dev.aaa.bbb", "pod-1")

    remote.save_file.assert_called_once()
    call_args = remote.save_file.call_args
    assert call_args[0][2] == "log.pod-1.jsonl"


def test_cached_sync_log_to_remote_noop_without_remote(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    cached = CachedSnapshotStorage(local, None)
    _save_exp(local, "app", "1.0.0-dev.aaa.bbb")

    entry = {"timestamp": "t1", "type": "metrics"}
    cached.append_log_entry("app", "1.0.0-dev.aaa.bbb", "pod-1", entry)
    # Should not raise
    cached.sync_log_to_remote("app", "1.0.0-dev.aaa.bbb", "pod-1")


# =========================================================================
# D. Writer ID (from experiment.py)
# =========================================================================

def test_get_writer_id_from_env_vmn_writer_id(monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.setenv("VMN_WRITER_ID", "my-pod")
    monkeypatch.delenv("HOSTNAME", raising=False)

    from version_stamp.cli.experiment import _get_writer_id
    assert _get_writer_id() == "my-pod"
    experiment._WRITER_ID = None


def test_get_writer_id_from_hostname(monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.setenv("HOSTNAME", "k8s-pod-abc")

    from version_stamp.cli.experiment import _get_writer_id
    assert _get_writer_id() == "k8s-pod-abc"
    experiment._WRITER_ID = None


def test_get_writer_id_fallback_uuid(monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    from version_stamp.cli.experiment import _get_writer_id
    wid = _get_writer_id()
    assert wid.startswith("w-")
    assert len(wid) == 10  # "w-" + 8 hex chars
    experiment._WRITER_ID = None


def test_get_writer_id_cached_across_calls(monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    from version_stamp.cli.experiment import _get_writer_id
    first = _get_writer_id()
    second = _get_writer_id()
    assert first == second
    experiment._WRITER_ID = None


# =========================================================================
# E. _app_name helper
# =========================================================================

def test_app_name_from_vcs():
    from version_stamp.cli.experiment import _app_name
    vcs = SimpleNamespace(name="myapp")
    assert _app_name(vcs) == "myapp"


def test_app_name_from_args_when_vcs_none():
    from version_stamp.cli.experiment import _app_name
    args = SimpleNamespace(name="myapp")
    assert _app_name(None, args) == "myapp"


def test_app_name_both_none():
    from version_stamp.cli.experiment import _app_name
    assert _app_name(None, None) is None


# =========================================================================
# F. Pod-unique verstr allocation
# =========================================================================

def test_allocate_verstr_with_writer_id(exp_storage, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.setenv("VMN_WRITER_ID", "pod-abc")

    from version_stamp.cli.experiment import _allocate_run_verstr
    verstr = _allocate_run_verstr(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    assert verstr == "1.0.0-dev.aaa.bbb.pod-abc"
    experiment._WRITER_ID = None


def test_allocate_verstr_writer_id_collision(exp_storage, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.setenv("VMN_WRITER_ID", "pod-abc")

    # Pre-save an experiment with the .pod-abc suffix
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb.pod-abc")

    from version_stamp.cli.experiment import _allocate_run_verstr
    verstr = _allocate_run_verstr(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    assert verstr == "1.0.0-dev.aaa.bbb.pod-abc.2"
    experiment._WRITER_ID = None


def test_allocate_verstr_single_user_first_run(exp_storage, monkeypatch):
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)

    from version_stamp.cli.experiment import _allocate_run_verstr
    verstr = _allocate_run_verstr(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    assert verstr == "1.0.0-dev.aaa.bbb"


def test_allocate_verstr_single_user_second_run(exp_storage, monkeypatch):
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    _save_exp(exp_storage, "app", "1.0.0-dev.aaa.bbb")

    from version_stamp.cli.experiment import _allocate_run_verstr
    verstr = _allocate_run_verstr(exp_storage, "app", "1.0.0-dev.aaa.bbb")
    assert verstr == "1.0.0-dev.aaa.bbb.r2"


# =========================================================================
# G. Snapshot-based experiment creation
# =========================================================================

def test_create_from_snapshot_reads_metadata(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({
        "verstr": "1.0.0-dev.aaa.bbb", "app_name": "myapp",
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }))

    from version_stamp.cli.experiment import _experiment_create_from_snapshot
    verstr, err = _experiment_create_from_snapshot(storage, "myapp", str(meta_path))
    assert err is None
    assert verstr is not None

    meta, _ = storage.load("myapp", verstr)
    assert meta["from_snapshot"] is True
    experiment._WRITER_ID = None


def test_create_from_snapshot_directory_path(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    snap_dir = tmp_path / "snapshot_dir"
    snap_dir.mkdir()
    (snap_dir / "vmn_metadata.yml").write_text(yaml.dump({
        "verstr": "1.0.0-dev.aaa.bbb", "app_name": "myapp",
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }))

    from version_stamp.cli.experiment import _experiment_create_from_snapshot
    verstr, err = _experiment_create_from_snapshot(storage, "myapp", str(snap_dir))
    assert err is None
    assert verstr is not None
    experiment._WRITER_ID = None


def test_create_from_snapshot_missing_file(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    from version_stamp.cli.experiment import _experiment_create_from_snapshot
    verstr, err = _experiment_create_from_snapshot(
        storage, "myapp", str(tmp_path / "nonexistent.yml")
    )
    assert verstr is None
    assert err == 1


def test_create_from_snapshot_missing_verstr(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)

    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({"app_name": "myapp", "base_version": "1.0.0"}))

    from version_stamp.cli.experiment import _experiment_create_from_snapshot
    verstr, err = _experiment_create_from_snapshot(storage, "myapp", str(meta_path))
    assert verstr is None
    assert err == 1
    experiment._WRITER_ID = None


def test_create_from_snapshot_with_note_and_extra(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({
        "verstr": "1.0.0-dev.aaa.bbb", "app_name": "myapp",
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }))

    from version_stamp.cli.experiment import _experiment_create_from_snapshot
    verstr, err = _experiment_create_from_snapshot(
        storage, "myapp", str(meta_path),
        note="my note",
        extra_create_data={"hypothesis": "test hypothesis"},
    )
    assert err is None

    log = storage.load_merged_log("myapp", verstr)
    create_entry = next(e for e in log if e.get("type") == "create")
    assert create_entry["note"] == "my note"
    assert create_entry["hypothesis"] == "test hypothesis"
    experiment._WRITER_ID = None


def test_create_from_snapshot_app_name_from_metadata(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({
        "verstr": "1.0.0-dev.aaa.bbb", "app_name": "from_meta",
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }))

    from version_stamp.cli.experiment import _experiment_create_from_snapshot
    verstr, err = _experiment_create_from_snapshot(
        storage, None, str(meta_path),
    )
    assert err is None

    meta, _ = storage.load("from_meta", verstr)
    assert meta["app_name"] == "from_meta"
    experiment._WRITER_ID = None


# =========================================================================
# H. _get_experiment_storage with experiment_dir
# =========================================================================

def test_get_experiment_storage_with_experiment_dir(tmp_path):
    from version_stamp.cli.experiment import _get_experiment_storage
    params = {"experiment_dir": str(tmp_path), "backend": "local"}
    storage = _get_experiment_storage(None, params)
    assert storage is not None
    # Verify it uses the right root by saving and checking
    storage.save("app", "v1", {"verstr": "v1", "timestamp": "t"}, {})
    assert storage.exists("app", "v1")


def test_get_experiment_storage_env_var(tmp_path, monkeypatch):
    from version_stamp.cli.experiment import _get_experiment_storage
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path))
    params = {"backend": "local"}
    storage = _get_experiment_storage(None, params)
    assert storage is not None
    storage.save("app", "v1", {"verstr": "v1", "timestamp": "t"}, {})
    assert storage.exists("app", "v1")


def test_get_experiment_storage_default_uses_vcs_root(tmp_path):
    from version_stamp.cli.experiment import _get_experiment_storage
    vcs = SimpleNamespace(vmn_root_path=str(tmp_path))
    params = {"backend": "local"}
    storage = _get_experiment_storage(vcs, params)
    assert storage is not None
    storage.save("app", "v1", {"verstr": "v1", "timestamp": "t"}, {})
    assert storage.exists("app", "v1")


# =========================================================================
# I. Entry.py git-free dispatch
# =========================================================================

def test_run_experiment_from_snapshot_create(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)

    from version_stamp.cli.entry import _run_experiment_from_snapshot

    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({
        "verstr": "1.0.0-dev.aaa.bbb", "app_name": "myapp",
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }))

    args = SimpleNamespace(
        action="create",
        name="myapp",
        from_snapshot=str(meta_path),
        backend="local",
        bucket=None,
        prefix="vmn-experiments",
        endpoint_url=None,
        experiment_dir=str(tmp_path),
        note="test note",
        file=None,
        metrics=None,
        writer_id=None,
    )
    ret = _run_experiment_from_snapshot(args)
    assert ret == 0
    experiment._WRITER_ID = None


def test_run_experiment_from_snapshot_sets_writer_id(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)

    from version_stamp.cli.entry import _run_experiment_from_snapshot

    meta_path = tmp_path / "vmn_metadata.yml"
    meta_path.write_text(yaml.dump({
        "verstr": "1.0.0-dev.aaa.bbb", "app_name": "myapp",
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }))

    args = SimpleNamespace(
        action="create",
        name="myapp",
        from_snapshot=str(meta_path),
        backend="local",
        bucket=None,
        prefix="vmn-experiments",
        endpoint_url=None,
        experiment_dir=str(tmp_path),
        note=None,
        file=None,
        metrics=None,
        writer_id="my-pod",
    )
    ret = _run_experiment_from_snapshot(args)
    assert ret == 0
    assert os.environ.get("VMN_WRITER_ID") == "my-pod"
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    experiment._WRITER_ID = None


def test_run_experiment_from_snapshot_unsupported_action(tmp_path, monkeypatch):
    import version_stamp.cli.experiment as experiment
    experiment._WRITER_ID = None

    from version_stamp.cli.entry import _run_experiment_from_snapshot

    args = SimpleNamespace(
        action="diff",
        name="myapp",
        from_snapshot="/fake/path",
        backend="local",
        bucket=None,
        prefix="vmn-experiments",
        endpoint_url=None,
        experiment_dir=str(tmp_path),
        writer_id=None,
    )
    ret = _run_experiment_from_snapshot(args)
    assert ret == 1
    experiment._WRITER_ID = None
