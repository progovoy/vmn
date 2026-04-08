#!/usr/bin/env python3
"""Snapshot storage and operations for dev versions."""
import datetime
import hashlib
import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

import yaml

from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


class SnapshotStorage(ABC):
    @abstractmethod
    def save(self, app_name, verstr, metadata, patches):
        ...

    @abstractmethod
    def load(self, app_name, verstr):
        ...

    @abstractmethod
    def list_snapshots(self, app_name):
        ...


class LocalSnapshotStorage(SnapshotStorage):
    def __init__(self, vmn_root_path):
        self.vmn_root_path = vmn_root_path

    def _snapshot_base_dir(self, app_name):
        return os.path.join(
            self.vmn_root_path, ".vmn",
            app_name.replace("/", os.sep), "snapshots",
        )

    def _snapshot_dir(self, app_name, verstr):
        safe_verstr = verstr.replace("+", "_plus_")
        return os.path.join(self._snapshot_base_dir(app_name), safe_verstr)

    def save(self, app_name, verstr, metadata, patches):
        snap_dir = self._snapshot_dir(app_name, verstr)
        Path(snap_dir).mkdir(parents=True, exist_ok=True)

        with open(os.path.join(snap_dir, "metadata.yml"), "w") as f:
            yaml.dump(metadata, f, sort_keys=True)

        if patches.get("working_tree"):
            with open(os.path.join(snap_dir, "working_tree.patch"), "w") as f:
                f.write(patches["working_tree"])

        if patches.get("local_commits"):
            with open(os.path.join(snap_dir, "local_commits.patch"), "w") as f:
                f.write(patches["local_commits"])

    def load(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        if not os.path.isdir(snap_dir):
            return None, None

        with open(os.path.join(snap_dir, "metadata.yml")) as f:
            metadata = yaml.safe_load(f)

        patches = {}
        wt_path = os.path.join(snap_dir, "working_tree.patch")
        if os.path.isfile(wt_path):
            with open(wt_path) as f:
                patches["working_tree"] = f.read()

        lc_path = os.path.join(snap_dir, "local_commits.patch")
        if os.path.isfile(lc_path):
            with open(lc_path) as f:
                patches["local_commits"] = f.read()

        return metadata, patches

    def list_snapshots(self, app_name):
        base = self._snapshot_base_dir(app_name)
        if not os.path.isdir(base):
            return []

        results = []
        for entry in sorted(os.listdir(base)):
            meta_path = os.path.join(base, entry, "metadata.yml")
            if os.path.isfile(meta_path):
                with open(meta_path) as f:
                    meta = yaml.safe_load(f)
                results.append(meta)
        return results

    def update_note(self, app_name, verstr, note):
        snap_dir = self._snapshot_dir(app_name, verstr)
        meta_path = os.path.join(snap_dir, "metadata.yml")
        if not os.path.isfile(meta_path):
            return False

        with open(meta_path) as f:
            metadata = yaml.safe_load(f)

        metadata["note"] = note
        with open(meta_path, "w") as f:
            yaml.dump(metadata, f, sort_keys=True)

        return True


class S3SnapshotStorage(SnapshotStorage):
    def __init__(self, bucket, prefix="vmn-snapshots"):
        try:
            import boto3  # noqa: F401
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 snapshot storage. "
                "Install it with: pip install boto3"
            )
        self.bucket = bucket
        self.prefix = prefix

    def save(self, app_name, verstr, metadata, patches):
        raise NotImplementedError("S3 snapshot storage is not yet implemented")

    def load(self, app_name, verstr):
        raise NotImplementedError("S3 snapshot storage is not yet implemented")

    def list_snapshots(self, app_name):
        raise NotImplementedError("S3 snapshot storage is not yet implemented")


class WandbSnapshotStorage(SnapshotStorage):
    def __init__(self, project):
        try:
            import wandb  # noqa: F401
        except ImportError:
            raise ImportError(
                "wandb is required for Weights & Biases snapshot storage. "
                "Install it with: pip install wandb"
            )
        self.project = project

    def save(self, app_name, verstr, metadata, patches):
        raise NotImplementedError("W&B snapshot storage is not yet implemented")

    def load(self, app_name, verstr):
        raise NotImplementedError("W&B snapshot storage is not yet implemented")

    def list_snapshots(self, app_name):
        raise NotImplementedError("W&B snapshot storage is not yet implemented")


class MLflowSnapshotStorage(SnapshotStorage):
    def __init__(self, project):
        try:
            import mlflow  # noqa: F401
        except ImportError:
            raise ImportError(
                "mlflow is required for MLflow snapshot storage. "
                "Install it with: pip install mlflow"
            )
        self.project = project

    def save(self, app_name, verstr, metadata, patches):
        raise NotImplementedError("MLflow snapshot storage is not yet implemented")

    def load(self, app_name, verstr):
        raise NotImplementedError("MLflow snapshot storage is not yet implemented")

    def list_snapshots(self, app_name):
        raise NotImplementedError("MLflow snapshot storage is not yet implemented")


def get_snapshot_storage(backend, vmn_root_path=None, bucket=None, project=None):
    if backend == "local":
        if not vmn_root_path:
            raise ValueError("vmn_root_path is required for local backend")
        return LocalSnapshotStorage(vmn_root_path)
    elif backend == "s3":
        if not bucket:
            raise ValueError("--bucket is required for s3 backend")
        return S3SnapshotStorage(bucket)
    elif backend == "wandb":
        if not project:
            raise ValueError("--project is required for wandb backend")
        return WandbSnapshotStorage(project)
    elif backend == "mlflow":
        if not project:
            raise ValueError("--project is required for mlflow backend")
        return MLflowSnapshotStorage(project)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def _get_storage(vcs, params):
    return get_snapshot_storage(
        params.get("backend", "local"),
        vmn_root_path=vcs.vmn_root_path,
        bucket=params.get("bucket"),
        project=params.get("project"),
    )


def _compute_diff_hash(diff_output):
    if not diff_output:
        return "0000000"
    return hashlib.sha1(diff_output.encode()).hexdigest()[:7]


def _generate_patches(backend):
    patches = {}

    try:
        wt_diff = backend._be.git.diff("HEAD")
        if wt_diff.strip():
            patches["working_tree"] = wt_diff
    except Exception:
        VMN_LOGGER.debug("Failed to generate working tree diff", exc_info=True)

    if backend.remote_active_branch is not None:
        try:
            local_commits_diff = backend._be.git.format_patch(
                "--stdout",
                f"{backend.remote_active_branch}..{backend.active_branch}",
            )
            if local_commits_diff.strip():
                patches["local_commits"] = local_commits_diff
        except Exception:
            VMN_LOGGER.debug(
                "Failed to generate local commits patch", exc_info=True
            )

    return patches


def _compute_verstr(base_version, commit_hash, patches):
    h = hashlib.sha1()
    has_content = False
    for key in ("working_tree", "local_commits"):
        if patches.get(key):
            h.update(patches[key].encode())
            has_content = True

    diff_hash = h.hexdigest()[:7] if has_content else "0000000"
    return f"{base_version}-dev.{commit_hash[:7]}.{diff_hash}"


@measure_runtime_decorator
def snapshot_create(vcs, params, note=None):
    from version_stamp.cli.commands import _get_repo_status
    from version_stamp.cli.output import get_dirty_states

    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "repos_exist_locally", "detached", "pending", "outgoing",
        "version_not_matched", "dirty_deps", "deps_synced_with_conf",
    }
    status = _get_repo_status(vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.error("Error getting repo status")
        return 1

    dirty_states = list(get_dirty_states(optional_status, status))
    if not dirty_states:
        VMN_LOGGER.info("No local changes to snapshot")
        return 0

    ver_infos = vcs.ver_infos_from_repo
    tag_name = vcs.selected_tag
    if tag_name not in ver_infos:
        VMN_LOGGER.error("No stamped version found for this app")
        return 1

    ver_info = ver_infos[tag_name]["ver_info"]
    if vcs.root_context:
        base_version = str(ver_info["stamping"]["root_app"]["version"])
    else:
        base_version = ver_info["stamping"]["app"]["_version"]

    be = vcs.backend
    commit_hash = be.changeset()

    patches = _generate_patches(be)
    if not patches:
        VMN_LOGGER.info("No patch content to snapshot")
        return 0

    verstr = _compute_verstr(base_version, commit_hash, patches)

    storage = _get_storage(vcs, params)

    try:
        remote_url = be.remote()
    except Exception:
        remote_url = None

    metadata = {
        "verstr": verstr,
        "base_version": base_version,
        "base_commit": commit_hash,
        "branch": be.active_branch,
        "remote": remote_url,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "note": note,
        "app_name": vcs.name,
        "dirty_states": dirty_states,
        "has_working_tree_patch": "working_tree" in patches,
        "has_local_commits_patch": "local_commits" in patches,
    }

    storage.save(vcs.name, verstr, metadata, patches)

    VMN_LOGGER.info(f"Created snapshot: {verstr}")
    print(verstr)
    return 0


@measure_runtime_decorator
def snapshot_list(vcs, params):
    storage = _get_storage(vcs, params)

    snapshots = storage.list_snapshots(vcs.name)
    if not snapshots:
        VMN_LOGGER.info(f"No snapshots found for {vcs.name}")
        return 0

    for meta in snapshots:
        note_str = f" - {meta['note']}" if meta.get("note") else ""
        print(f"{meta['verstr']}  [{meta['timestamp']}]{note_str}")

    return 0


@measure_runtime_decorator
def snapshot_show(vcs, params, verstr):
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1

    storage = _get_storage(vcs, params)

    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1

    print(yaml.dump(metadata, sort_keys=True))
    if patches.get("working_tree"):
        print("--- Working tree patch ---")
        print(patches["working_tree"])
    if patches.get("local_commits"):
        print("--- Local commits patch ---")
        print(patches["local_commits"])

    return 0


@measure_runtime_decorator
def snapshot_note(vcs, params, verstr, note):
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1
    if note is None:
        VMN_LOGGER.error("Must specify --note")
        return 1

    storage = _get_storage(vcs, params)

    if not hasattr(storage, "update_note"):
        VMN_LOGGER.error("Note editing only supported for local backend")
        return 1

    if storage.update_note(vcs.name, verstr, note):
        VMN_LOGGER.info(f"Updated note for {verstr}")
        return 0
    else:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1
