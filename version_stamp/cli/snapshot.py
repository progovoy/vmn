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


def _relative_timestamp(iso_ts):
    """Convert ISO timestamp to relative format like '2m ago', '3h ago', '5d ago'."""
    try:
        dt = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return iso_ts
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        VMN_LOGGER.debug("Failed to parse timestamp %s", iso_ts, exc_info=True)
        return iso_ts


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

    def exists(self, app_name, verstr):
        """Check if a snapshot exists without loading its full content."""
        metadata, _ = self.load(app_name, verstr)
        return metadata is not None

    @abstractmethod
    def update_note(self, app_name, verstr, note):
        ...

    @abstractmethod
    def delete(self, app_name, verstr):
        ...

    @abstractmethod
    def load_file(self, app_name, verstr, filename):
        """Load an auxiliary file from a snapshot directory. Returns bytes or None."""
        ...

    @abstractmethod
    def save_file(self, app_name, verstr, filename, data):
        """Save an auxiliary file into a snapshot directory. data is bytes or str."""
        ...

    @abstractmethod
    def save_artifact_file(self, app_name, verstr, src_path):
        """Copy an artifact file into the snapshot's artifacts subdirectory."""
        ...

    @abstractmethod
    def list_artifact_files(self, app_name, verstr):
        """Return the filesystem path to the artifacts directory, or None."""
        ...


def _write_patches_to_dir(directory, patches):
    if patches.get("working_tree"):
        with open(os.path.join(directory, "working_tree.patch"), "w") as f:
            f.write(patches["working_tree"])
    if patches.get("local_commits"):
        with open(os.path.join(directory, "local_commits.patch"), "w") as f:
            f.write(patches["local_commits"])
    if patches.get("untracked_files"):
        with open(os.path.join(directory, "untracked_files.tar.gz"), "wb") as f:
            f.write(patches["untracked_files"])


def _read_patches_from_dir(directory):
    patches = {}
    wt_path = os.path.join(directory, "working_tree.patch")
    if os.path.isfile(wt_path):
        with open(wt_path) as f:
            patches["working_tree"] = f.read()
    lc_path = os.path.join(directory, "local_commits.patch")
    if os.path.isfile(lc_path):
        with open(lc_path) as f:
            patches["local_commits"] = f.read()
    ut_path = os.path.join(directory, "untracked_files.tar.gz")
    if os.path.isfile(ut_path):
        with open(ut_path, "rb") as f:
            patches["untracked_files"] = f.read()
    return patches


class LocalSnapshotStorage(SnapshotStorage):
    def __init__(self, vmn_root_path, subdir="snapshots"):
        self.vmn_root_path = vmn_root_path
        self._subdir = subdir

    def _snapshot_base_dir(self, app_name):
        return os.path.join(
            self.vmn_root_path, ".vmn",
            app_name.replace("/", os.sep), self._subdir,
        )

    def _snapshot_dir(self, app_name, verstr):
        safe_verstr = verstr.replace("+", "_plus_")
        return os.path.join(self._snapshot_base_dir(app_name), safe_verstr)

    def exists(self, app_name, verstr):
        meta_path = os.path.join(self._snapshot_dir(app_name, verstr), "metadata.yml")
        return os.path.isfile(meta_path)

    def save(self, app_name, verstr, metadata, patches):
        snap_dir = self._snapshot_dir(app_name, verstr)
        Path(snap_dir).mkdir(parents=True, exist_ok=True)

        with open(os.path.join(snap_dir, "metadata.yml"), "w") as f:
            yaml.dump(metadata, f, sort_keys=True)

        _write_patches_to_dir(snap_dir, patches)

        dep_patches = patches.get("deps", {})
        for dep_path, dp in dep_patches.items():
            safe_dep = dep_path.replace(os.sep, "_").replace("/", "_")
            dep_dir = os.path.join(snap_dir, "deps", safe_dep)
            Path(dep_dir).mkdir(parents=True, exist_ok=True)
            _write_patches_to_dir(dep_dir, dp)

    def load(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        if not os.path.isdir(snap_dir):
            return None, None

        with open(os.path.join(snap_dir, "metadata.yml")) as f:
            metadata = yaml.safe_load(f)

        patches = _read_patches_from_dir(snap_dir)

        deps_dir = os.path.join(snap_dir, "deps")
        if os.path.isdir(deps_dir):
            dep_patches = {}
            for dep_name in os.listdir(deps_dir):
                dep_dir = os.path.join(deps_dir, dep_name)
                if os.path.isdir(dep_dir):
                    dp = _read_patches_from_dir(dep_dir)
                    if dp:
                        dep_patches[dep_name] = dp
            if dep_patches:
                patches["deps"] = dep_patches

        return metadata, patches

    def list_snapshots(self, app_name):
        base = self._snapshot_base_dir(app_name)
        if not os.path.isdir(base):
            return []

        results = []
        for entry in os.listdir(base):
            meta_path = os.path.join(base, entry, "metadata.yml")
            if os.path.isfile(meta_path):
                with open(meta_path) as f:
                    meta = yaml.safe_load(f)
                results.append(meta)
        results.sort(key=lambda m: m.get("timestamp", ""))
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

    def delete(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        if os.path.isdir(snap_dir):
            shutil.rmtree(snap_dir, ignore_errors=True)

    def load_file(self, app_name, verstr, filename):
        path = os.path.join(self._snapshot_dir(app_name, verstr), filename)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def save_file(self, app_name, verstr, filename, data):
        snap_dir = self._snapshot_dir(app_name, verstr)
        Path(snap_dir).mkdir(parents=True, exist_ok=True)
        path = os.path.join(snap_dir, filename)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(path, mode) as f:
            f.write(data)

    def save_artifact_file(self, app_name, verstr, src_path):
        art_dir = os.path.join(self._snapshot_dir(app_name, verstr), "artifacts")
        os.makedirs(art_dir, exist_ok=True)
        shutil.copy2(src_path, os.path.join(art_dir, os.path.basename(src_path)))

    def list_artifact_files(self, app_name, verstr):
        art_dir = os.path.join(self._snapshot_dir(app_name, verstr), "artifacts")
        if os.path.isdir(art_dir):
            return art_dir
        return None


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
        self._put_patches(prefix, patches)

        dep_patches = patches.get("deps", {})
        for dep_path, dp in dep_patches.items():
            safe_dep = dep_path.replace(os.sep, "_").replace("/", "_")
            self._put_patches(f"{prefix}/deps/{safe_dep}", dp)

    def _put_patches(self, prefix, patches):
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
        if patches.get("untracked_files"):
            self._s3.put_object(
                Bucket=self.bucket,
                Key=f"{prefix}/untracked_files.tar.gz",
                Body=patches["untracked_files"],
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
            VMN_LOGGER.warning(f"S3 error loading snapshot: {e}")
            VMN_LOGGER.debug("S3 load failed", exc_info=True)
            return None, None

        patches = self._get_patches(prefix)

        dep_patches = {}
        dep_prefix = f"{prefix}/deps/"
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self.bucket, Prefix=dep_prefix, Delimiter="/"
            ):
                for cp in page.get("CommonPrefixes", []):
                    dep_name = cp["Prefix"][len(dep_prefix):].rstrip("/")
                    dp = self._get_patches(cp["Prefix"].rstrip("/"))
                    if dp:
                        dep_patches[dep_name] = dp
        except Exception:
            VMN_LOGGER.debug("Failed to list S3 dep patches", exc_info=True)

        if dep_patches:
            patches["deps"] = dep_patches

        return metadata, patches

    def _get_patches(self, prefix):
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
        try:
            resp = self._s3.get_object(
                Bucket=self.bucket,
                Key=f"{prefix}/untracked_files.tar.gz",
            )
            patches["untracked_files"] = resp["Body"].read()
        except Exception:
            pass
        return patches

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
                    VMN_LOGGER.warning(
                        f"Failed to read S3 snapshot metadata: {meta_key}"
                    )
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

    def delete(self, app_name, verstr):
        prefix = self._key_prefix(app_name, verstr)
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{prefix}/"):
            for obj in page.get("Contents", []):
                self._s3.delete_object(Bucket=self.bucket, Key=obj["Key"])

    def load_file(self, app_name, verstr, filename):
        prefix = self._key_prefix(app_name, verstr)
        try:
            resp = self._s3.get_object(
                Bucket=self.bucket, Key=f"{prefix}/{filename}"
            )
            return resp["Body"].read()
        except Exception:
            return None

    def save_file(self, app_name, verstr, filename, data):
        prefix = self._key_prefix(app_name, verstr)
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        self._s3.put_object(
            Bucket=self.bucket, Key=f"{prefix}/{filename}", Body=body,
        )

    def save_artifact_file(self, app_name, verstr, src_path):
        prefix = self._key_prefix(app_name, verstr)
        basename = os.path.basename(src_path)
        with open(src_path, "rb") as f:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=f"{prefix}/artifacts/{basename}",
                Body=f.read(),
            )

    def list_artifact_files(self, app_name, verstr):
        return None


class CachedSnapshotStorage(SnapshotStorage):
    """Local-first storage with optional S3 sync. All ops hit local disk;
    S3 provides durability and distribution."""

    def __init__(self, local_storage, remote_storage=None):
        self._local = local_storage
        self._remote = remote_storage

    def save(self, app_name, verstr, metadata, patches):
        self._local.save(app_name, verstr, metadata, patches)
        if self._remote:
            try:
                self._remote.save(app_name, verstr, metadata, patches)
            except Exception:
                VMN_LOGGER.warning("Failed to sync snapshot to remote storage")
                VMN_LOGGER.debug("Remote save failed", exc_info=True)

    def load(self, app_name, verstr):
        meta, patches = self._local.load(app_name, verstr)
        if meta is not None:
            return meta, patches
        if self._remote:
            meta, patches = self._remote.load(app_name, verstr)
            if meta is not None:
                self._local.save(app_name, verstr, meta, patches)
            return meta, patches
        return None, None

    def exists(self, app_name, verstr):
        if self._local.exists(app_name, verstr):
            return True
        if self._remote:
            return self._remote.exists(app_name, verstr)
        return False

    def list_snapshots(self, app_name):
        local_snaps = self._local.list_snapshots(app_name)
        seen = {m["verstr"] for m in local_snaps}
        all_snaps = list(local_snaps)
        if self._remote:
            try:
                for m in self._remote.list_snapshots(app_name):
                    if m["verstr"] not in seen:
                        all_snaps.append(m)
                        seen.add(m["verstr"])
            except Exception:
                VMN_LOGGER.debug("Failed to list remote snapshots", exc_info=True)
        all_snaps.sort(key=lambda m: m.get("timestamp", ""))
        return all_snaps

    def update_note(self, app_name, verstr, note):
        ok = self._local.update_note(app_name, verstr, note)
        if self._remote:
            try:
                self._remote.update_note(app_name, verstr, note)
            except Exception:
                VMN_LOGGER.debug("Failed to update note on remote", exc_info=True)
        return ok

    def delete(self, app_name, verstr):
        self._local.delete(app_name, verstr)
        if self._remote:
            try:
                self._remote.delete(app_name, verstr)
            except Exception:
                VMN_LOGGER.debug("Failed to delete from remote", exc_info=True)

    def load_file(self, app_name, verstr, filename):
        data = self._local.load_file(app_name, verstr, filename)
        if data is not None:
            return data
        if self._remote:
            data = self._remote.load_file(app_name, verstr, filename)
            if data is not None:
                self._local.save_file(app_name, verstr, filename, data)
            return data
        return None

    def save_file(self, app_name, verstr, filename, data):
        self._local.save_file(app_name, verstr, filename, data)
        if self._remote:
            try:
                self._remote.save_file(app_name, verstr, filename, data)
            except Exception:
                VMN_LOGGER.debug("Failed to save file to remote", exc_info=True)

    def save_artifact_file(self, app_name, verstr, src_path):
        self._local.save_artifact_file(app_name, verstr, src_path)
        if self._remote:
            try:
                self._remote.save_artifact_file(app_name, verstr, src_path)
            except Exception:
                VMN_LOGGER.debug("Failed to save artifact to remote", exc_info=True)

    def list_artifact_files(self, app_name, verstr):
        return self._local.list_artifact_files(app_name, verstr)


def get_snapshot_storage(backend, vmn_root_path=None, bucket=None,
                         prefix="vmn-snapshots", endpoint_url=None,
                         subdir="snapshots"):
    local = None
    remote = None

    if vmn_root_path:
        local = LocalSnapshotStorage(vmn_root_path, subdir=subdir)

    if bucket:
        remote = S3SnapshotStorage(bucket, prefix=prefix, endpoint_url=endpoint_url)

    if backend == "local":
        if not local:
            raise ValueError("vmn_root_path is required for local backend")
        return CachedSnapshotStorage(local, remote)
    elif backend == "s3":
        if not remote:
            raise ValueError("--bucket is required for s3 backend")
        if local:
            return CachedSnapshotStorage(local, remote)
        return remote
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


def _resolve_verstr(storage, app_name, verstr, latest=False):
    """Resolve a version string shorthand to a full verstr.

    - If latest=True or verstr == "latest": return most recent by timestamp
    - If verstr doesn't exactly match: try unique prefix match
    - Otherwise: pass through as-is
    Returns (resolved_verstr, error_message_or_None).
    """
    if latest or verstr == "latest":
        snapshots = storage.list_snapshots(app_name)
        if not snapshots:
            return None, f"No snapshots found for {app_name}"
        most_recent = max(snapshots, key=lambda m: m.get("timestamp", ""))
        return most_recent["verstr"], None

    if verstr is None:
        return None, None

    # Try exact match first (fast path — no need to load full data)
    if storage.exists(app_name, verstr):
        return verstr, None

    # Try prefix match
    snapshots = storage.list_snapshots(app_name)
    matches = [m for m in snapshots if m["verstr"].startswith(verstr)]
    if len(matches) == 1:
        return matches[0]["verstr"], None
    if len(matches) > 1:
        return None, (
            f"Ambiguous prefix '{verstr}': matches {len(matches)} snapshots. "
            f"Be more specific."
        )
    return None, f"Snapshot '{verstr}' not found"


def _ensure_trailing_newline(s):
    """git apply/am require patches to end with a newline."""
    return s if s.endswith("\n") else s + "\n"


def _generate_patches(backend):
    patches = {}

    try:
        wt_diff = backend._be.git.diff("HEAD")
        if wt_diff.strip():
            patches["working_tree"] = _ensure_trailing_newline(wt_diff)
    except Exception:
        VMN_LOGGER.debug("Failed to generate working tree diff", exc_info=True)

    if backend.remote_active_branch is not None:
        try:
            local_commits_diff = backend._be.git.format_patch(
                "--stdout",
                f"{backend.remote_active_branch}..{backend.active_branch}",
            )
            if local_commits_diff.strip():
                patches["local_commits"] = _ensure_trailing_newline(local_commits_diff)
        except Exception:
            VMN_LOGGER.debug(
                "Failed to generate local commits patch", exc_info=True
            )

    try:
        untracked_tar = _collect_untracked_tarball(backend.repo_path)
        if untracked_tar:
            patches["untracked_files"] = untracked_tar
    except Exception:
        VMN_LOGGER.debug("Failed to collect untracked files", exc_info=True)

    return patches


def _generate_dep_patches(vcs):
    from version_stamp.backends.factory import get_client

    configured_deps = getattr(vcs, "configured_deps", None)
    if not configured_deps:
        return {}

    dep_patches = {}
    for dep_path in configured_deps:
        if dep_path == ".":
            continue
        full_path = os.path.join(vcs.vmn_root_path, dep_path)
        if not os.path.isdir(full_path):
            continue
        try:
            dep_be, err = get_client(full_path, vcs.be_type)
            if err or not dep_be:
                continue
            dp = _generate_patches(dep_be)
            if dp:
                dep_patches[dep_path] = dp
        except Exception:
            VMN_LOGGER.debug(f"Failed to generate patches for dep {dep_path}", exc_info=True)

    return dep_patches


def _collect_untracked_tarball(repo_path):
    """Collect untracked non-ignored files into an in-memory tar.gz."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=repo_path,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    buf = io.BytesIO()
    file_count = 0
    with tarfile.open(mode="w:gz", fileobj=buf) as tar:
        for rel_path in result.stdout.strip().split("\n"):
            if not rel_path:
                continue
            # Skip vmn's own state directory
            if rel_path.startswith(".vmn/") or rel_path == ".vmn":
                continue
            abs_path = os.path.join(repo_path, rel_path)
            if os.path.isfile(abs_path):
                tar.add(abs_path, arcname=rel_path)
                file_count += 1

    if file_count == 0:
        return None
    return buf.getvalue()


def _extract_untracked_tarball(dest, tarball_bytes):
    """Extract untracked files tarball into dest directory."""
    buf = io.BytesIO(tarball_bytes)
    with tarfile.open(mode="r:gz", fileobj=buf) as tar:
        tar.extractall(path=dest)


def _list_tarball_members(tarball_bytes):
    """List file names in a tarball."""
    buf = io.BytesIO(tarball_bytes)
    with tarfile.open(mode="r:gz", fileobj=buf) as tar:
        return sorted(m.name for m in tar.getmembers())


def _compute_verstr(base_version, commit_hash, patches):
    h = hashlib.sha256()
    has_content = False
    for key in ("working_tree", "local_commits"):
        if patches.get(key):
            h.update(patches[key].encode())
            has_content = True
    if patches.get("untracked_files"):
        h.update(patches["untracked_files"])
        has_content = True

    for dep_path in sorted(patches.get("deps", {})):
        dp = patches["deps"][dep_path]
        for key in ("working_tree", "local_commits"):
            if dp.get(key):
                h.update(dp[key].encode())
                has_content = True
        if dp.get("untracked_files"):
            h.update(dp["untracked_files"])
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
                input=_ensure_trailing_newline(patches["local_commits"]),
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
                input=_ensure_trailing_newline(patches["working_tree"]),
                capture_output=True, text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply working tree patch: {result.stderr}"
                )
                return 1

        if patches.get("untracked_files"):
            try:
                _extract_untracked_tarball(vcs.vmn_root_path, patches["untracked_files"])
            except Exception:
                VMN_LOGGER.warning("Failed to extract untracked files from snapshot")
                VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

    _apply_dep_patches(vcs, metadata, patches)

    VMN_LOGGER.info(f"Restored dev version {metadata['verstr']} of {vcs.name}")
    return 0


def _apply_dep_patches(vcs, metadata, patches):
    dep_patches = patches.get("deps", {})
    if not dep_patches:
        return

    changesets = metadata.get("changesets", {})
    for dep_name, dp in dep_patches.items():
        dep_info = None
        for cs_path, cs_info in changesets.items():
            safe = cs_path.replace(os.sep, "_").replace("/", "_")
            if safe == dep_name or cs_path == dep_name:
                dep_info = cs_info
                dep_path = cs_path
                break

        if not dep_info:
            VMN_LOGGER.warning(f"No changeset info for dep {dep_name}, skipping patches")
            continue

        full_path = os.path.join(vcs.vmn_root_path, dep_path)
        if not os.path.isdir(full_path):
            VMN_LOGGER.warning(f"Dep directory {dep_path} not found, skipping patches")
            continue

        dep_hash = dep_info.get("hash")
        if dep_hash:
            try:
                result = subprocess.run(
                    ["git", "checkout", dep_hash],
                    capture_output=True, text=True, cwd=full_path,
                )
                if result.returncode != 0:
                    VMN_LOGGER.warning(f"Failed to checkout dep {dep_path} at {dep_hash[:7]}")
            except Exception:
                VMN_LOGGER.debug(f"Failed to checkout dep {dep_path}", exc_info=True)

        _apply_patches_to_workdir(full_path, dp)


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


def gather_create_data(vcs):
    """Gather common data needed by snapshot/experiment create.

    Returns (base_version, commit_hash, patches, dirty_states, ver_info, error_code).
    error_code is non-None when the caller should return early.
    """
    from version_stamp.cli.commands import _get_repo_status
    from version_stamp.cli.output import get_dirty_states

    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "repos_exist_locally", "detached", "pending", "outgoing",
        "version_not_matched", "dirty_deps", "deps_synced_with_conf",
    }
    status = _get_repo_status(vcs, expected_status, optional_status)
    if status.error:
        name = vcs.name or "<app_name>"
        VMN_LOGGER.error(
            f"Cannot create snapshot: '{name}' has not been stamped yet. "
            f"Run 'vmn stamp -r patch {name}' first."
        )
        return None, None, None, None, None, 1

    dirty_states = list(get_dirty_states(optional_status, status))

    ver_infos = vcs.ver_infos_from_repo
    tag_name = vcs.selected_tag
    if tag_name not in ver_infos:
        name = vcs.name or "<app_name>"
        VMN_LOGGER.error(
            f"No stamped version found for '{name}'. "
            f"Run 'vmn stamp -r patch {name}' first."
        )
        return None, None, None, None, None, 1

    ver_info = ver_infos[tag_name]["ver_info"]
    if vcs.root_context:
        base_version = str(ver_info["stamping"]["root_app"]["version"])
    else:
        base_version = ver_info["stamping"]["app"]["_version"]

    be = vcs.backend
    commit_hash = be.changeset()

    patches = _generate_patches(be)
    dep_patches = _generate_dep_patches(vcs)
    if dep_patches:
        patches["deps"] = dep_patches

    has_content = (
        any(k != "deps" for k in patches) or bool(dep_patches)
    )
    if not patches or not has_content:
        print("No local changes to snapshot (working tree is clean)")
        return None, None, None, None, None, 0

    return base_version, commit_hash, patches, dirty_states, ver_info, None


@measure_runtime_decorator
def snapshot_create(vcs, params, note=None, user_meta=None):
    base_version, commit_hash, patches, dirty_states, ver_info, err = \
        gather_create_data(vcs)
    if err is not None:
        return err

    verstr = _compute_verstr(base_version, commit_hash, patches)

    storage = _get_storage(vcs, params)

    be = vcs.backend
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
        "has_untracked_files": "untracked_files" in patches,
        "has_dep_patches": bool(patches.get("deps")),
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
    storage = _get_storage(vcs, params)
    snapshots = storage.list_snapshots(vcs.name)
    if not snapshots:
        VMN_LOGGER.info(f"No snapshots found for {vcs.name}")
        return 0

    filters = _parse_meta_args(params.get("filter")) if params.get("filter") else None

    idx = 0
    for meta in snapshots:
        if filters:
            user_meta = meta.get("user_meta", {})
            if not all(str(user_meta.get(k)) == v for k, v in filters.items()):
                continue

        idx += 1
        if params.get("verbose"):
            ts_display = meta["timestamp"]
        else:
            ts_display = _relative_timestamp(meta["timestamp"])
        note_str = f" - {meta['note']}" if meta.get("note") else ""
        meta_str = ""
        if meta.get("user_meta"):
            meta_str = " " + " ".join(
                f"{k}={v}" for k, v in meta["user_meta"].items()
            )
        print(f"[{idx}] {meta['verstr']}  ({ts_display}){note_str}{meta_str}")

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
    if patches.get("untracked_files"):
        print("--- Untracked files ---")
        for name in _list_tarball_members(patches["untracked_files"]):
            print(f"  {name}")

    if patches.get("deps"):
        for dep_name, dp in patches["deps"].items():
            print(f"\n--- Dep: {dep_name} ---")
            if dp.get("working_tree"):
                print(f"  working tree patch: {len(dp['working_tree'])} bytes")
            if dp.get("local_commits"):
                print(f"  local commits patch: {len(dp['local_commits'])} bytes")
            if dp.get("untracked_files"):
                print(f"  untracked files: {len(_list_tarball_members(dp['untracked_files']))} files")

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


def _synthesize_stamped_version(vcs, verstr):
    """Synthesize empty snapshot metadata for a stamped (non-dev) version.

    A stamped version is a clean checkout at a tag — no patches.
    Returns (metadata, patches) or (None, None) if not resolvable.
    """
    if "-dev." in verstr:
        return None, None

    try:
        tag_name, ver_infos = vcs.get_version_info_from_verstr(verstr)
    except Exception:
        VMN_LOGGER.debug(f"Failed to resolve stamped version {verstr}", exc_info=True)
        return None, None

    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        return None, None

    ver_info = ver_infos[tag_name]["ver_info"]
    changesets = ver_info["stamping"]["app"].get("changesets", {})
    commit_hash = changesets.get(".", {}).get("hash", "")
    if not commit_hash:
        return None, None

    metadata = {
        "verstr": verstr,
        "base_version": verstr,
        "base_commit": commit_hash,
        "branch": changesets.get(".", {}).get("branch", ""),
        "remote": changesets.get(".", {}).get("remote", ""),
        "timestamp": "stamped",
        "note": None,
        "app_name": vcs.name,
        "changesets": changesets,
    }
    return metadata, {}


def _load_or_synthesize(storage, vcs, verstr):
    """Load a snapshot from storage, or synthesize for stamped versions."""
    meta, patches = storage.load(vcs.name, verstr)
    if meta is not None:
        return meta, patches

    # Not in storage — try to resolve as a stamped version
    meta, patches = _synthesize_stamped_version(vcs, verstr)
    if meta is not None:
        return meta, patches

    return None, None


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

    meta1, patches1 = _load_or_synthesize(storage, vcs, verstr1)
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
        meta2, patches2 = _load_or_synthesize(storage, vcs, verstr2)
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

    ut1 = patches1.get("untracked_files")
    ut2 = patches2.get("untracked_files")
    if ut1 or ut2:
        names1 = _list_tarball_members(ut1) if ut1 else []
        names2 = _list_tarball_members(ut2) if ut2 else []
        if names1 != names2:
            print("--- untracked files ---")
            for line in difflib.unified_diff(
                [n + "\n" for n in names1],
                [n + "\n" for n in names2],
                fromfile=f"{verstr1}/untracked",
                tofile=f"{verstr2}/untracked",
            ):
                print(line, end="")
            print()
        elif names1:
            print("untracked files: identical file list")

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
    if patches.get("untracked_files"):
        with open(os.path.join(directory, "untracked_files.tar.gz"), "wb") as f:
            f.write(patches["untracked_files"])


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
    VMN_LOGGER.warning(
        f"Shallow fetch failed for {commit_hash[:7]}, falling back to full clone"
    )
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
            input=_ensure_trailing_newline(patches["local_commits"]),
            capture_output=True, text=True, cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply local commits: {result.stderr}")

    if patches.get("working_tree"):
        result = subprocess.run(
            ["git", "apply"],
            input=_ensure_trailing_newline(patches["working_tree"]),
            capture_output=True, text=True, cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply working tree patch: {result.stderr}")

    if patches.get("untracked_files"):
        try:
            _extract_untracked_tarball(dest, patches["untracked_files"])
        except Exception:
            VMN_LOGGER.debug("Failed to extract untracked files in workdir", exc_info=True)


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

    # Fallback for old snapshots without stored untracked files:
    # copy from live working tree if HEAD matches base_commit
    if not patches.get("untracked_files") and vcs and hasattr(vcs, 'vmn_root_path'):
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

    # Export dependencies and apply dep patches
    changesets = metadata.get("changesets", {})
    dep_patches = patches.get("deps", {})
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
            continue

        safe_dep = dep_path.replace(os.sep, "_").replace("/", "_")
        dp = dep_patches.get(safe_dep) or dep_patches.get(dep_path)
        if dp:
            _apply_patches_to_workdir(dep_dest, dp)

    # Write metadata
    meta_path = os.path.join(output_path, "vmn_metadata.yml")
    with open(meta_path, "w") as f:
        yaml.dump(metadata, f, sort_keys=True)

    return 0


def _strip_git_dirs(root_path):
    """Remove all .git directories to make export fully offline."""
    for dirpath, dirnames, _ in os.walk(root_path, topdown=True):
        if ".git" in dirnames:
            shutil.rmtree(os.path.join(dirpath, ".git"), ignore_errors=True)
            dirnames.remove(".git")


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

        _strip_git_dirs(dest)

        if is_tarball:
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(dest, arcname=safe_verstr)

        VMN_LOGGER.info(f"Exported snapshot to {output_path}")
        print(output_path)
        return 0
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
