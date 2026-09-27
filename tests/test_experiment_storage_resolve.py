"""Tests for the unified resolve_experiment_storage() helper (refactor item).

Covers:
1. in_repo_default: SDK registers a model; vmn model list (no flags/env) sees it.
2. vmn_experiment_dir_wins: VMN_EXPERIMENT_DIR overrides the repo root.
3. bucket_env_gives_s3: VMN_EXPERIMENT_BUCKET → S3 backend via moto.
4. flags_beat_env: explicit dir= flag wins over VMN_EXPERIMENT_DIR.
5. import_mlflow_in_repo: import-mlflow into an in-repo app, same storage as exp list.

All tests are Docker-free: they use VMN_WORKING_DIR to point at a temp dir with
.vmn (satisfying resolve_root_path), or pass dir= / storage= explicitly.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

BUCKET = "vmn-test-bucket"
PREFIX = "vmn-experiments"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _storage_root(storage):
    """Return the vmn_root_path regardless of whether storage is Local or Cached."""
    # CachedSnapshotStorage wraps local in ._local; LocalSnapshotStorage has .vmn_root_path
    local = getattr(storage, "_local", storage)
    return getattr(local, "vmn_root_path", None)


def _is_s3(storage):
    """True if *storage* ultimately talks to S3 (no local root)."""
    from version_stamp.cli.snapshot_storage_s3 import S3SnapshotStorage
    if isinstance(storage, S3SnapshotStorage):
        return True
    # BufferedRemoteStorage has a ._remote
    remote = getattr(storage, "_remote", None)
    if remote is not None and isinstance(remote, S3SnapshotStorage):
        return True
    return False

def _make_repo(tmp_path):
    """Create a minimal repo-like dir (has .vmn) and return its path string."""
    vmn_dir = tmp_path / ".vmn"
    vmn_dir.mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


def _local_storage(path):
    from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
    return LocalSnapshotStorage(path, subdir="experiments")


def _register_fake_run(storage, app_name, verstr):
    """Plant a minimal experiment record so resolve_ref can locate the run."""
    metadata = {
        "app": app_name,
        "verstr": verstr,
        "timestamp": "2024-01-01T00:00:00.000000",
    }
    storage.create_exclusive(app_name, verstr, metadata, {})


# ---------------------------------------------------------------------------
# Test 1: In-repo default — SDK-registered model visible to vmn model list
# ---------------------------------------------------------------------------

def test_in_repo_default_sdk_model_visible_to_vmn_model_list(tmp_path, monkeypatch):
    """register_model into repo storage; model_run_without_repo (no flags/env)
    auto-detects repo root and sees the model."""
    repo_root = _make_repo(tmp_path)
    monkeypatch.setenv("VMN_WORKING_DIR", repo_root)
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_BUCKET", raising=False)

    storage = _local_storage(repo_root)
    _register_fake_run(storage, "myapp", "1.0.0")

    from vmn_exp.registry.store import ensure_model, register_version
    ensure_model(storage, "mymodel")
    register_version(storage, "mymodel", {"app": "myapp", "verstr": "1.0.0"})

    # Call the CLI handler with *no* --dir and no env override.
    # _get_storage must auto-detect the repo root.
    from vmn_exp.registry.cli import model_run_without_repo
    import io, contextlib

    args = SimpleNamespace(
        action="list",
        dir=None,
        bucket=None,
        prefix="vmn-experiments",
        endpoint_url=None,
        json=True,
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = model_run_without_repo(args)

    assert rc == 0, f"model list failed: {buf.getvalue()}"
    import json as _json
    names = _json.loads(buf.getvalue())
    assert "mymodel" in names


# ---------------------------------------------------------------------------
# Test 2: VMN_EXPERIMENT_DIR wins over repo root
# ---------------------------------------------------------------------------

def test_vmn_experiment_dir_wins(tmp_path, monkeypatch):
    """VMN_EXPERIMENT_DIR should be used instead of the repo root."""
    repo_root = _make_repo(tmp_path / "repo")
    exp_dir = str(tmp_path / "custom_exp")
    os.makedirs(exp_dir, exist_ok=True)

    monkeypatch.setenv("VMN_WORKING_DIR", repo_root)
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", exp_dir)
    monkeypatch.delenv("VMN_EXPERIMENT_BUCKET", raising=False)

    from version_stamp.core.experiment_storage_resolve import resolve_experiment_storage
    storage = resolve_experiment_storage()

    root = _storage_root(storage)
    assert root is not None and root.startswith(exp_dir)


# ---------------------------------------------------------------------------
# Test 3: VMN_EXPERIMENT_BUCKET env → S3 backend (moto)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def test_bucket_env_gives_s3_backend(tmp_path, monkeypatch, _aws_creds):
    """VMN_EXPERIMENT_BUCKET (no dir) → S3 backend."""
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", BUCKET)
    monkeypatch.setenv("VMN_EXPERIMENT_PREFIX", PREFIX)

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)

        from version_stamp.core.experiment_storage_resolve import resolve_experiment_storage
        storage = resolve_experiment_storage()

    assert _is_s3(storage), f"Expected S3 backend, got {type(storage).__name__}"


# ---------------------------------------------------------------------------
# Test 4: Explicit dir= flag beats VMN_EXPERIMENT_DIR
# ---------------------------------------------------------------------------

def test_flags_beat_env(tmp_path, monkeypatch):
    """Explicit dir= parameter beats VMN_EXPERIMENT_DIR."""
    env_dir = str(tmp_path / "env_exp")
    flag_dir = str(tmp_path / "flag_exp")
    os.makedirs(env_dir, exist_ok=True)
    os.makedirs(flag_dir, exist_ok=True)

    monkeypatch.setenv("VMN_EXPERIMENT_DIR", env_dir)
    monkeypatch.delenv("VMN_EXPERIMENT_BUCKET", raising=False)

    from version_stamp.core.experiment_storage_resolve import resolve_experiment_storage
    storage = resolve_experiment_storage(dir=flag_dir)

    root = _storage_root(storage)
    assert root is not None and root.startswith(flag_dir)


# ---------------------------------------------------------------------------
# Test 5: import-mlflow in-repo app visible in same storage as exp list
# ---------------------------------------------------------------------------

def test_import_mlflow_in_repo_visible_to_exp_storage(tmp_path, monkeypatch):
    """import-mlflow with no --dir uses the repo root; the imported run lives
    in the same storage that _local_storage(repo_root) returns."""
    repo_root = _make_repo(tmp_path)
    monkeypatch.setenv("VMN_WORKING_DIR", repo_root)
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_BUCKET", raising=False)

    # Build a minimal mlruns fixture: one experiment, one run.
    mlruns = tmp_path / "mlruns"
    exp1 = mlruns / "1"
    exp1.mkdir(parents=True)
    run_id = "aabbccdd1234" + "0" * 20  # 32-char run id
    (exp1 / "meta.yaml").write_text(
        "artifact_location: ./artifacts\nexperiment_id: '1'\nname: test_exp\n"
        "lifecycle_stage: active\nlast_update_time: 1700000000000\n"
        "creation_time: 1700000000000\n"
    )
    run_dir = exp1 / run_id
    run_dir.mkdir()
    (run_dir / "meta.yaml").write_text(
        f"artifact_uri: ./artifacts\nend_time: 1700001000000\nentry_point_name: ''\n"
        f"experiment_id: '1'\nlifecycle_stage: active\n"
        f"run_id: {run_id}\nrun_uuid: {run_id}\n"
        "source_name: ''\nsource_type: 4\nstart_time: 1700000000000\nstatus: 3\n"
        "tags: []\nuser_id: tester\n"
    )
    (run_dir / "metrics").mkdir()
    (run_dir / "params").mkdir()
    (run_dir / "tags").mkdir()

    from vmn_exp.importers.cli import import_mlflow_run_without_repo
    args = SimpleNamespace(
        mlruns=str(mlruns),
        tracking_uri=None,
        name="myapp",
        experiment=[],
        include_deleted=False,
        dry_run=False,
        workers=1,
        skip_artifacts=True,
        experiment_dir=None,  # no explicit dir → falls back to repo root
        bucket=None,
        prefix="vmn-experiments",
        endpoint_url=None,
        backend="local",
    )
    rc = import_mlflow_run_without_repo(args)
    assert rc == 0

    # The run should now be in the repo's experiment storage.
    storage = _local_storage(repo_root)
    verstrs = storage.list_verstrs("myapp")
    assert len(verstrs) >= 1
