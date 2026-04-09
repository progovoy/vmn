#!/usr/bin/env python3
"""Snapshot storage and operations for dev versions."""
import datetime
import difflib
import hashlib
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
            resp = getattr(e, "response", None)
            error_code = (resp or {}).get("Error", {}).get("Code") if resp else None
            if error_code == "NoSuchKey" or "NoSuchKey" in str(e):
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


def get_snapshot_storage(backend, vmn_root_path=None, bucket=None,
                         prefix="vmn-snapshots", endpoint_url=None):
    if backend == "local":
        if not vmn_root_path:
            raise ValueError("vmn_root_path is required for local backend")
        return LocalSnapshotStorage(vmn_root_path)
    elif backend == "s3":
        if not bucket:
            raise ValueError("--bucket is required for s3 backend")
        return S3SnapshotStorage(bucket, prefix=prefix, endpoint_url=endpoint_url)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def _get_storage(vcs, params):
    return get_snapshot_storage(
        params.get("backend", "local"),
        vmn_root_path=vcs.vmn_root_path,
        bucket=params.get("bucket"),
        prefix=params.get("prefix", "vmn-snapshots"),
        endpoint_url=params.get("endpoint_url"),
    )


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


def _apply_snapshot_patches(vcs, params, metadata, patches):
    """Apply snapshot patches to restore a dev version state."""
    base_commit = metadata["base_commit"]

    if not params.get("deps_only"):
        try:
            vcs.backend.checkout(rev=base_commit)
        except Exception:
            VMN_LOGGER.error(
                f"Failed to checkout base commit {base_commit[:7]}"
            )
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
            return 1

        if patches.get("local_commits"):
            result = subprocess.run(
                ["git", "am", "--3way"],
                input=patches["local_commits"],
                capture_output=True, text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply local commits patch: {result.stderr}"
                )
                return 1

        if patches.get("working_tree"):
            result = subprocess.run(
                ["git", "apply", "--3way"],
                input=patches["working_tree"],
                capture_output=True, text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply working tree patch: {result.stderr}"
                )
                return 1

    VMN_LOGGER.info(f"Restored dev version {metadata['verstr']} of {vcs.name}")
    return 0


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
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": note,
        "app_name": vcs.name,
        "dirty_states": dirty_states,
        "has_working_tree_patch": "working_tree" in patches,
        "has_local_commits_patch": "local_commits" in patches,
    }
    if user_meta:
        metadata["user_meta"] = user_meta

    changesets = ver_info["stamping"]["app"].get("changesets", {})
    if changesets:
        metadata["changesets"] = changesets

    storage.save(vcs.name, verstr, metadata, patches)

    VMN_LOGGER.info(f"Created snapshot: {verstr}")
    print(verstr)
    return 0


@measure_runtime_decorator
def snapshot_list(vcs, params):
    local_storage = LocalSnapshotStorage(vcs.vmn_root_path)
    local_snaps = local_storage.list_snapshots(vcs.name)
    all_snaps = {m["verstr"]: m for m in local_snaps}

    bucket = params.get("bucket")
    if bucket:
        try:
            s3_storage = S3SnapshotStorage(
                bucket,
                prefix=params.get("prefix", "vmn-snapshots"),
                endpoint_url=params.get("endpoint_url"),
            )
            for m in s3_storage.list_snapshots(vcs.name):
                if m["verstr"] not in all_snaps:
                    all_snaps[m["verstr"]] = m
        except Exception:
            VMN_LOGGER.debug("S3 listing failed", exc_info=True)

    snapshots = sorted(all_snaps.values(), key=lambda m: m.get("timestamp", ""))
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

    storage = _get_storage(vcs, params)
    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1

    return _apply_snapshot_patches(vcs, params, metadata, patches)


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
            tool, vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
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


def _diff_with_external_tool(tool, vcs, verstr1, meta1, patches1,
                              verstr2, meta2, patches2):
    """Materialize both snapshots as workdirs and launch external diff tool."""
    tmpdir = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        left_dir = os.path.join(tmpdir, verstr1.replace("+", "_plus_"))
        right_dir = os.path.join(tmpdir, verstr2.replace("+", "_plus_"))

        left_ok = _materialize_workdir(vcs, meta1, patches1, left_dir) == 0
        right_ok = _materialize_workdir(vcs, meta2, patches2, right_dir) == 0

        if not left_ok or not right_ok:
            # Fallback: write patches to dirs
            if not left_ok:
                os.makedirs(left_dir, exist_ok=True)
                _write_snapshot_to_dir(left_dir, meta1, patches1)
            if not right_ok:
                os.makedirs(right_dir, exist_ok=True)
                _write_snapshot_to_dir(right_dir, meta2, patches2)

        result = subprocess.run([tool, left_dir, right_dir])
        return result.returncode
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_snapshot_to_dir(directory, metadata, patches):
    """Write snapshot metadata and patches to a directory (fallback)."""
    with open(os.path.join(directory, "metadata.yml"), "w") as f:
        yaml.dump(metadata, f, sort_keys=True)
    if patches.get("working_tree"):
        with open(os.path.join(directory, "working_tree.patch"), "w") as f:
            f.write(patches["working_tree"])
    if patches.get("local_commits"):
        with open(os.path.join(directory, "local_commits.patch"), "w") as f:
            f.write(patches["local_commits"])


def _shallow_clone_at(dest, remote, commit_hash):
    """Create a shallow clone at a specific commit."""
    # Try shallow fetch first (works with servers that support it)
    os.makedirs(dest, exist_ok=True)
    result = subprocess.run(
        ["git", "init"],
        capture_output=True, text=True, cwd=dest,
    )
    if result.returncode != 0:
        VMN_LOGGER.error(f"git init failed in {dest}: {result.stderr}")
        return 1

    result = subprocess.run(
        ["git", "fetch", "--depth", "1", remote, commit_hash],
        capture_output=True, text=True, cwd=dest,
    )
    if result.returncode == 0:
        result = subprocess.run(
            ["git", "checkout", "FETCH_HEAD"],
            capture_output=True, text=True, cwd=dest,
        )
        if result.returncode == 0:
            return 0

    # Fallback: full clone + checkout (for local repos / servers without SHA1 fetch)
    shutil.rmtree(dest, ignore_errors=True)
    result = subprocess.run(
        ["git", "clone", "--no-checkout", remote, dest],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        VMN_LOGGER.error(f"git clone failed: {result.stderr}")
        return 1

    result = subprocess.run(
        ["git", "checkout", commit_hash],
        capture_output=True, text=True, cwd=dest,
    )
    if result.returncode != 0:
        VMN_LOGGER.error(f"git checkout {commit_hash[:7]} failed: {result.stderr}")
        return 1

    return 0


def _apply_patches_to_workdir(dest, patches):
    """Apply local_commits and working_tree patches to a workdir."""
    if patches.get("local_commits"):
        result = subprocess.run(
            ["git", "am", "--3way"],
            input=patches["local_commits"],
            capture_output=True, text=True, cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply local commits: {result.stderr}")

    if patches.get("working_tree"):
        result = subprocess.run(
            ["git", "apply"],
            input=patches["working_tree"],
            capture_output=True, text=True, cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply working tree patch: {result.stderr}")


def _copy_untracked_files(repo_path, dest):
    """Copy untracked non-ignored files from repo to dest."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=repo_path,
    )
    if result.returncode != 0:
        return

    for rel_path in result.stdout.strip().split("\n"):
        if not rel_path:
            continue
        src = os.path.join(repo_path, rel_path)
        dst = os.path.join(dest, rel_path)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def _resolve_remote(remote, vcs):
    """Resolve a remote URL, converting relative paths to absolute."""
    if not remote:
        return remote
    vmn_root = vcs.vmn_root_path if vcs and hasattr(vcs, 'vmn_root_path') else None
    if vmn_root and not remote.startswith(("http://", "https://", "git://", "ssh://", "git@")):
        # Relative or local path — resolve against vmn_root
        resolved = os.path.normpath(os.path.join(vmn_root, remote))
        if os.path.exists(resolved):
            return resolved
    return remote


def _materialize_workdir(vcs, metadata, patches, output_path):
    """Materialize a patch snapshot into a complete working directory."""
    base_commit = metadata.get("base_commit")
    remote = metadata.get("remote")

    if not base_commit:
        VMN_LOGGER.error("Snapshot metadata missing base_commit")
        return 1

    if not remote:
        VMN_LOGGER.error("Snapshot metadata missing remote URL")
        return 1

    remote = _resolve_remote(remote, vcs)

    err = _shallow_clone_at(output_path, remote, base_commit)
    if err:
        return err

    _apply_patches_to_workdir(output_path, patches)

    # Copy untracked files if current working tree matches the snapshot
    if vcs and hasattr(vcs, 'vmn_root_path'):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=vcs.vmn_root_path,
            )
            current_head = result.stdout.strip()
            if current_head.startswith(base_commit[:7]) or base_commit.startswith(current_head[:7]):
                _copy_untracked_files(vcs.vmn_root_path, output_path)
            else:
                VMN_LOGGER.debug(
                    f"HEAD ({current_head[:7]}) != base_commit ({base_commit[:7]}), "
                    "skipping untracked files"
                )
        except Exception:
            VMN_LOGGER.debug("Failed to copy untracked files", exc_info=True)

    # Export dependencies
    changesets = metadata.get("changesets", {})
    for dep_path, dep_info in changesets.items():
        if dep_path == ".":
            continue

        dep_hash = dep_info.get("hash")
        dep_remote = dep_info.get("remote")
        if not dep_hash or not dep_remote:
            VMN_LOGGER.warning(f"Dependency {dep_path} missing hash or remote, skipping")
            continue

        dep_remote = _resolve_remote(dep_remote, vcs)

        dep_dest = os.path.join(output_path, dep_path)
        err = _shallow_clone_at(dep_dest, dep_remote, dep_hash)
        if err:
            VMN_LOGGER.warning(f"Failed to export dependency {dep_path}")

    # Write metadata
    meta_path = os.path.join(output_path, "vmn_metadata.yml")
    with open(meta_path, "w") as f:
        yaml.dump(metadata, f, sort_keys=True)

    return 0


@measure_runtime_decorator
def snapshot_export(vcs, params, verstr, output_path):
    """Export a snapshot as a complete working directory or tarball."""
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
        output_path = safe_verstr

    is_tarball = output_path.endswith(".tar.gz") or output_path.endswith(".tgz")

    if is_tarball:
        tmpdir = tempfile.mkdtemp(prefix="vmn-export-")
        dest = os.path.join(tmpdir, safe_verstr)
    else:
        tmpdir = None
        dest = output_path

    try:
        err = _materialize_workdir(vcs, metadata, patches, dest)
        if err:
            return err

        if is_tarball:
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(dest, arcname=safe_verstr)

        VMN_LOGGER.info(f"Exported snapshot to {output_path}")
        print(output_path)
        return 0
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
