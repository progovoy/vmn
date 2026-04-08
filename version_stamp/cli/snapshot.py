#!/usr/bin/env python3
"""Snapshot storage and operations for dev versions."""
import datetime
import difflib
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
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

    @abstractmethod
    def update_note(self, app_name, verstr, note):
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
    def __init__(self, bucket, prefix="vmn-snapshots", endpoint_url=None):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 snapshot storage. "
                "Install it with: pip install boto3"
            )
        self.bucket = bucket
        self.prefix = prefix
        client_kwargs = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self._s3 = boto3.client("s3", **client_kwargs)

    def _key_prefix(self, app_name, verstr=None):
        safe_app = app_name.replace("/", "_")
        if verstr:
            safe_verstr = verstr.replace("+", "_plus_")
            return f"{self.prefix}/{safe_app}/{safe_verstr}"
        return f"{self.prefix}/{safe_app}"

    def save(self, app_name, verstr, metadata, patches):
        prefix = self._key_prefix(app_name, verstr)
        self._s3.put_object(
            Bucket=self.bucket,
            Key=f"{prefix}/metadata.yml",
            Body=yaml.dump(metadata, sort_keys=True).encode("utf-8"),
        )
        if patches.get("working_tree"):
            self._s3.put_object(
                Bucket=self.bucket,
                Key=f"{prefix}/working_tree.patch",
                Body=patches["working_tree"].encode("utf-8"),
            )
        if patches.get("local_commits"):
            self._s3.put_object(
                Bucket=self.bucket,
                Key=f"{prefix}/local_commits.patch",
                Body=patches["local_commits"].encode("utf-8"),
            )

    def load(self, app_name, verstr):
        prefix = self._key_prefix(app_name, verstr)
        try:
            resp = self._s3.get_object(
                Bucket=self.bucket, Key=f"{prefix}/metadata.yml"
            )
            metadata = yaml.safe_load(resp["Body"].read().decode("utf-8"))
        except Exception as e:
            if "NoSuchKey" in str(type(e).__name__) or "NoSuchKey" in str(e):
                return None, None
            VMN_LOGGER.debug("S3 load failed", exc_info=True)
            return None, None

        patches = {}
        for patch_name in ("working_tree", "local_commits"):
            try:
                resp = self._s3.get_object(
                    Bucket=self.bucket,
                    Key=f"{prefix}/{patch_name}.patch",
                )
                patches[patch_name] = resp["Body"].read().decode("utf-8")
            except Exception:
                pass

        return metadata, patches

    def list_snapshots(self, app_name):
        prefix = self._key_prefix(app_name)
        results = []
        paginator = self._s3.get_paginator("list_objects_v2")

        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=f"{prefix}/", Delimiter="/"
        ):
            for common_prefix in page.get("CommonPrefixes", []):
                meta_key = f"{common_prefix['Prefix']}metadata.yml"
                try:
                    resp = self._s3.get_object(
                        Bucket=self.bucket, Key=meta_key
                    )
                    meta = yaml.safe_load(
                        resp["Body"].read().decode("utf-8")
                    )
                    results.append(meta)
                except Exception:
                    VMN_LOGGER.debug(
                        f"Failed to read {meta_key}", exc_info=True
                    )

        return sorted(results, key=lambda m: m.get("timestamp", ""))

    def update_note(self, app_name, verstr, note):
        metadata, patches = self.load(app_name, verstr)
        if metadata is None:
            return False
        metadata["note"] = note
        prefix = self._key_prefix(app_name, verstr)
        self._s3.put_object(
            Bucket=self.bucket,
            Key=f"{prefix}/metadata.yml",
            Body=yaml.dump(metadata, sort_keys=True).encode("utf-8"),
        )
        return True


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

    def update_note(self, app_name, verstr, note):
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

    def update_note(self, app_name, verstr, note):
        raise NotImplementedError("MLflow snapshot storage is not yet implemented")


def get_snapshot_storage(backend, vmn_root_path=None, bucket=None, project=None,
                         prefix="vmn-snapshots", endpoint_url=None):
    if backend == "local":
        if not vmn_root_path:
            raise ValueError("vmn_root_path is required for local backend")
        return LocalSnapshotStorage(vmn_root_path)
    elif backend == "s3":
        if not bucket:
            raise ValueError("--bucket is required for s3 backend")
        return S3SnapshotStorage(bucket, prefix=prefix, endpoint_url=endpoint_url)
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
        prefix=params.get("prefix", "vmn-snapshots"),
        endpoint_url=params.get("endpoint_url"),
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


def _parse_meta_args(meta_list):
    """Parse ['key=val', ...] into a dict."""
    if not meta_list:
        return {}
    result = {}
    for item in meta_list:
        if "=" not in item:
            VMN_LOGGER.error(f"Invalid --meta format: {item}. Expected key=value")
            raise ValueError(f"Invalid meta format: {item}")
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _build_user_meta(meta_args, meta_file):
    """Build user_meta dict from CLI --meta args and/or --meta-file."""
    result = {}
    if meta_file:
        with open(meta_file) as f:
            file_meta = yaml.safe_load(f)
        if isinstance(file_meta, dict):
            result.update(file_meta)
        else:
            VMN_LOGGER.error(
                f"--meta-file must contain a YAML mapping, got {type(file_meta).__name__}"
            )
            raise ValueError("Invalid meta file format")
    if meta_args:
        result.update(_parse_meta_args(meta_args))
    return result if result else None


@measure_runtime_decorator
def snapshot_create(vcs, params, note=None, user_meta=None):
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
    if user_meta:
        metadata["user_meta"] = user_meta

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

    filters = _parse_meta_args(params.get("filter")) if params.get("filter") else None

    for meta in snapshots:
        if filters:
            user_meta = meta.get("user_meta", {})
            if not all(str(user_meta.get(k)) == v for k, v in filters.items()):
                continue

        note_str = f" - {meta['note']}" if meta.get("note") else ""
        meta_str = ""
        if meta.get("user_meta"):
            meta_str = " " + " ".join(
                f"{k}={v}" for k, v in meta["user_meta"].items()
            )
        print(f"{meta['verstr']}  [{meta['timestamp']}]{note_str}{meta_str}")

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

    if storage.update_note(vcs.name, verstr, note):
        VMN_LOGGER.info(f"Updated note for {verstr}")
        return 0
    else:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1


@measure_runtime_decorator
def snapshot_restore(vcs, params, verstr):
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1

    from version_stamp.cli.output import _goto_dev_version
    return _goto_dev_version(vcs, params, verstr)


@measure_runtime_decorator
def snapshot_diff(vcs, params, verstr1, verstr2, tool=None):
    """Compare two snapshots. verstr2 can be 'current' to diff against working state."""
    if verstr1 is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1
    if verstr2 is None:
        VMN_LOGGER.error("Must specify --to version (or 'current')")
        return 1

    storage = _get_storage(vcs, params)

    meta1, patches1 = storage.load(vcs.name, verstr1)
    if meta1 is None:
        VMN_LOGGER.error(f"Snapshot {verstr1} not found")
        return 1

    if verstr2 == "current":
        patches2 = _generate_patches(vcs.backend)
        meta2 = {
            "verstr": "current",
            "timestamp": "now",
            "branch": vcs.backend.active_branch,
        }
    else:
        meta2, patches2 = storage.load(vcs.name, verstr2)
        if meta2 is None:
            VMN_LOGGER.error(f"Snapshot {verstr2} not found")
            return 1

    tool = tool or os.environ.get("VMN_DIFFTOOL")

    if tool:
        return _diff_with_external_tool(
            tool, verstr1, meta1, patches1, verstr2, meta2, patches2
        )
    else:
        return _diff_builtin(verstr1, meta1, patches1, verstr2, meta2, patches2)


def _diff_builtin(verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Print unified diff of two snapshots to stdout."""
    print(f"--- {verstr1}")
    print(f"+++ {verstr2}")
    print()

    all_keys = sorted(set(list(meta1.keys()) + list(meta2.keys())))
    meta_changes = []
    for key in all_keys:
        v1 = meta1.get(key)
        v2 = meta2.get(key)
        if v1 != v2:
            meta_changes.append(f"  {key}: {v1} -> {v2}")
    if meta_changes:
        print("Metadata changes:")
        for line in meta_changes:
            print(line)
        print()

    for patch_type in ("working_tree", "local_commits"):
        p1 = patches1.get(patch_type, "")
        p2 = patches2.get(patch_type, "")
        if p1 == p2:
            if p1:
                print(f"{patch_type}: identical")
            continue

        label = patch_type.replace("_", " ")
        diff_lines = difflib.unified_diff(
            p1.splitlines(keepends=True),
            p2.splitlines(keepends=True),
            fromfile=f"{verstr1}/{patch_type}.patch",
            tofile=f"{verstr2}/{patch_type}.patch",
        )
        print(f"--- {label} changes ---")
        for line in diff_lines:
            print(line, end="")
        print()

    return 0


def _diff_with_external_tool(tool, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Write snapshots to temp dirs and launch external diff tool."""
    tmpdir = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        left_dir = os.path.join(tmpdir, verstr1.replace("+", "_plus_"))
        right_dir = os.path.join(tmpdir, verstr2.replace("+", "_plus_"))
        os.makedirs(left_dir)
        os.makedirs(right_dir)

        _write_snapshot_to_dir(left_dir, meta1, patches1)
        _write_snapshot_to_dir(right_dir, meta2, patches2)

        result = subprocess.run([tool, left_dir, right_dir])
        return result.returncode
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_snapshot_to_dir(directory, metadata, patches):
    """Write snapshot metadata and patches to a directory."""
    with open(os.path.join(directory, "metadata.yml"), "w") as f:
        yaml.dump(metadata, f, sort_keys=True)
    if patches.get("working_tree"):
        with open(os.path.join(directory, "working_tree.patch"), "w") as f:
            f.write(patches["working_tree"])
    if patches.get("local_commits"):
        with open(os.path.join(directory, "local_commits.patch"), "w") as f:
            f.write(patches["local_commits"])


def _add_string_to_tar(tar, name, content):
    """Add a string as a file to a tarball."""
    data = content.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _generate_restore_script(metadata, patches):
    """Generate a shell script that restores the snapshot state."""
    base_commit = metadata.get("base_commit", "UNKNOWN")
    lines = [
        "#!/bin/bash",
        "# vmn snapshot restore script",
        f"# Snapshot: {metadata.get('verstr', 'unknown')}",
        f"# Created: {metadata.get('timestamp', 'unknown')}",
        f"# Branch: {metadata.get('branch', 'unknown')}",
        "",
        "set -e",
        "",
        f'echo "Checking out base commit {base_commit[:12]}..."',
        f"git checkout {base_commit}",
        "",
    ]
    if patches.get("local_commits"):
        lines.extend([
            'echo "Applying local commits..."',
            "git am --3way < local_commits.patch",
            "",
        ])
    if patches.get("working_tree"):
        lines.extend([
            'echo "Applying working tree changes..."',
            "git apply --3way < working_tree.patch",
            "",
        ])
    lines.append('echo "Snapshot restored successfully."')
    return "\n".join(lines) + "\n"


@measure_runtime_decorator
def snapshot_export(vcs, params, verstr, output_path):
    """Export a snapshot as a self-contained .tar.gz archive."""
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1

    storage = _get_storage(vcs, params)
    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1

    safe_verstr = verstr.replace("+", "_plus_")
    if output_path is None:
        output_path = f"{safe_verstr}.tar.gz"

    restore_script = _generate_restore_script(metadata, patches)

    with tarfile.open(output_path, "w:gz") as tar:
        _add_string_to_tar(
            tar, f"{safe_verstr}/metadata.yml",
            yaml.dump(metadata, sort_keys=True),
        )
        if patches.get("working_tree"):
            _add_string_to_tar(
                tar, f"{safe_verstr}/working_tree.patch",
                patches["working_tree"],
            )
        if patches.get("local_commits"):
            _add_string_to_tar(
                tar, f"{safe_verstr}/local_commits.patch",
                patches["local_commits"],
            )
        _add_string_to_tar(
            tar, f"{safe_verstr}/restore.sh",
            restore_script,
        )

    VMN_LOGGER.info(f"Exported snapshot to {output_path}")
    print(output_path)
    return 0
