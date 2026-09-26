#!/usr/bin/env python3
"""Snapshot storage and operations for dev versions."""
import datetime
import os
import shutil
import subprocess  # kept so tests can patch snap.subprocess.run
import sys
import tarfile
import tempfile

import yaml

# The storage backends live in their own modules; these names stay importable
# from here for existing callers.
from version_stamp.cli.snapshot_storage import SnapshotStorage  # noqa: F401
from version_stamp.cli.snapshot_storage_cached import (  # noqa: F401
    CachedSnapshotStorage,
    get_snapshot_storage,
)
from version_stamp.cli.snapshot_storage_files import (  # noqa: F401
    read_patches_from_dir as _read_patches_from_dir,
)
from version_stamp.cli.snapshot_storage_files import (  # noqa: F401
    write_patches_to_dir as _write_patches_to_dir,
)
from version_stamp.cli.snapshot_storage_local import (  # noqa: F401
    LocalSnapshotStorage,
)
from version_stamp.cli.snapshot_storage_s3 import S3SnapshotStorage  # noqa: F401
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import now_iso, sha256_file

# Re-export dev-version helpers that stamping callers already import from here.
# The actual implementations live in version_stamp.devversion.*
from version_stamp.devversion.apply import (  # noqa: F401
    _apply_dep_patches,
    _apply_patches_to_workdir,
    _apply_snapshot_patches,
    _reset_worktree,
)
from version_stamp.devversion.capture import (  # noqa: F401
    _compute_diff_hash,
    _compute_verstr,
    _DIFF_HASH_LENGTHS,
    _format_dev_verstr,
    _generate_dep_patches,
    _generate_patches,
    _stored_diff_hash,
    _unique_snapshot_verstr,
    gather_create_data,
)
from version_stamp.devversion.materialize import (  # noqa: F401
    _clone_at,
    _clone_local_at,
    _commit_exists,
    _diff_real_tree,
    _diff_with_external_tool,
    _git,
    _git_ok,
    _LOCAL_GIT_TIMEOUT_SEC,
    _materialize_for_diff,
    _materialize_workdir,
    _NETWORK_GIT_TIMEOUT_SEC,
    _predates_untracked_capture,
    _resolve_remote,
    _shallow_clone_at,
    _strip_git_dirs,
    _write_snapshot_to_dir,
    get_git_difftool,
    render_tree_diff,
)
from version_stamp.devversion.untracked import (  # noqa: F401
    _collect_untracked_tarball,
    _DEFAULT_MAX_FILE_MB,
    _ensure_trailing_newline,
    _DEFAULT_MAX_TOTAL_MB,
    _extract_untracked_tarball,
    _fmt_size,
    _hash_untracked_content,
    _list_tarball_members,
    _load_untracked_cache,
    _mb_from_env,
    _store_untracked_cache,
    _UNTRACKED_CACHE_FILE,
    _untracked_candidates,
    _untracked_caps,
    _within_caps,
    copy_untracked_files,
    untracked_payload,
)

# These two are pure helpers that the core write path needs as well, so they
# live in core.utils now. The old private names stay importable from here.
_now_iso = now_iso
_sha256_file = sha256_file


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


def _get_storage(vcs, params):
    return get_snapshot_storage(
        params.get("backend", "local"),
        vmn_root_path=vcs.vmn_root_path,
        bucket=params.get("bucket"),
        prefix=params.get("prefix", "vmn-snapshots"),
        endpoint_url=params.get("endpoint_url"),
    )


def _resolve_verstr(storage, app_name, verstr, latest=False, kind="snapshot"):
    """Resolve a version reference to a full verstr.

    Accepts: ``--latest`` / ``"latest"`` / ``"@latest"`` (most recent),
    ``"@N"`` (the N-th row shown by ``list``, 1-indexed, oldest-first), an exact
    verstr, a unique dev-verstr prefix, or a stamped (non-dev) version passed
    through untouched. Returns ``(resolved_verstr, error_message_or_None)``.
    """
    if latest or verstr in ("latest", "@latest"):
        snaps = storage.list_snapshots(app_name)
        if not snaps:
            return None, f"No {kind}s found for {app_name}"
        most_recent = max(snaps, key=lambda m: m.get("timestamp", ""))
        return most_recent["verstr"], None

    if verstr is None:
        return None, None

    if verstr.startswith("@"):
        idx_str = verstr[1:]
        if not idx_str.isdigit():
            return None, f"Invalid index reference '{verstr}' (use @N, e.g. @1)"
        n = int(idx_str)
        snaps = storage.list_snapshots(app_name)
        if n < 1 or n > len(snaps):
            return None, f"Index '{verstr}' out of range (1..{len(snaps)})"
        return snaps[n - 1]["verstr"], None

    if storage.exists(app_name, verstr):
        return verstr, None

    if "-dev." not in verstr:
        return verstr, None

    if hasattr(storage, "list_verstrs"):
        names = storage.list_verstrs(app_name)
    else:
        names = [m["verstr"] for m in storage.list_snapshots(app_name)]
    matches = sorted(v for v in names if v.startswith(verstr))
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        cands = ", ".join(matches)
        return None, (
            f"Ambiguous prefix '{verstr}': matches {len(matches)} {kind}s: {cands}"
        )
    return None, f"{kind.capitalize()} '{verstr}' not found"


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
    return result or None


def _skipped_untracked(patches):
    """Untracked paths left out by the size caps, deps prefixed by their path."""
    skipped = list(patches.get("untracked_skipped", []))
    for dep_path, dp in sorted(patches.get("deps", {}).items()):
        skipped.extend(f"{dep_path}/{p}" for p in dp.get("untracked_skipped", []))
    return skipped


def _build_snapshot_metadata(
    vcs,
    verstr,
    base_version,
    commit_hash,
    dirty_states,
    patches,
    ver_info,
    note=None,
    user_meta=None,
):
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
        "timestamp": _now_iso(),
        "note": note,
        "app_name": vcs.name,
        "dirty_states": dirty_states,
        "has_working_tree_patch": "working_tree" in patches,
        "has_local_commits_patch": "local_commits" in patches,
        "has_untracked_files": "untracked_files" in patches,
        "has_dep_patches": bool(patches.get("deps")),
    }
    diff_hash = _compute_diff_hash(patches)
    if diff_hash:
        metadata["diff_hash"] = diff_hash
    skipped = _skipped_untracked(patches)
    if skipped:
        metadata["untracked_skipped"] = skipped
    if user_meta:
        metadata["user_meta"] = user_meta

    changesets = ver_info["stamping"]["app"].get("changesets", {})
    if changesets:
        metadata["changesets"] = changesets
    return metadata


@measure_runtime_decorator
def snapshot_create(vcs, params, note=None, user_meta=None):
    (
        base_version,
        commit_hash,
        patches,
        dirty_states,
        ver_info,
        err,
    ) = gather_create_data(vcs)
    if err is not None:
        return err

    storage = _get_storage(vcs, params)
    verstr = _unique_snapshot_verstr(
        storage, vcs.name, base_version, commit_hash, _compute_diff_hash(patches)
    )
    metadata = _build_snapshot_metadata(
        vcs,
        verstr,
        base_version,
        commit_hash,
        dirty_states,
        patches,
        ver_info,
        note=note,
        user_meta=user_meta,
    )
    storage.save(vcs.name, verstr, metadata, patches)

    VMN_LOGGER.info(f"Created snapshot: {verstr}")
    print(verstr)
    return 0


def _save_safety_snapshot(vcs, params, target_verstr):
    """Snapshot the current dirty state before a restore overwrites it."""
    (
        base_version,
        commit_hash,
        patches,
        dirty_states,
        ver_info,
        err,
    ) = gather_create_data(vcs)
    if err is not None:
        return None

    storage = _get_storage(vcs, params)
    verstr = _unique_snapshot_verstr(
        storage, vcs.name, base_version, commit_hash, _compute_diff_hash(patches)
    )
    if verstr == target_verstr:
        return None

    metadata = _build_snapshot_metadata(
        vcs,
        verstr,
        base_version,
        commit_hash,
        dirty_states,
        patches,
        ver_info,
        note="auto-saved before restore",
    )
    storage.save(vcs.name, verstr, metadata, patches)
    return verstr


def _restore_with_safety_net(vcs, params, metadata, patches):
    """Apply a restore, first auto-snapshotting any dirty work it would clobber."""
    saved = _save_safety_snapshot(vcs, params, metadata.get("verstr"))
    if saved:
        VMN_LOGGER.info(
            f"Current work saved as {saved} — restore it anytime with: "
            f"vmn snapshot restore {vcs.name} -v {saved}"
        )
    if not params.get("deps_only"):
        _reset_worktree(vcs)
    return _apply_snapshot_patches(vcs, params, metadata, patches)


@measure_runtime_decorator
def snapshot_restore(vcs, params, verstr):
    storage = _get_storage(vcs, params)
    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1
    ret = _restore_with_safety_net(vcs, params, metadata, patches)
    if ret == 0:
        VMN_LOGGER.info(f"Restored snapshot {verstr}")
    return ret


@measure_runtime_decorator
def snapshot_list(vcs, params):
    storage = _get_storage(vcs, params)
    snapshots = storage.list_snapshots(vcs.name)
    if not snapshots:
        VMN_LOGGER.info(f"No snapshots found for {vcs.name}")
        return 0

    numbered = list(enumerate(snapshots, 1))
    last = params.get("last")
    if last:
        numbered = numbered[-last:]

    filters = _parse_meta_args(params.get("filter")) if params.get("filter") else None

    for idx, meta in numbered:
        if filters:
            user_meta = meta.get("user_meta", {})
            if not all(str(user_meta.get(k)) == v for k, v in filters.items()):
                continue

        if params.get("verbose"):
            ts_display = meta["timestamp"]
        else:
            ts_display = _relative_timestamp(meta["timestamp"])
        note_str = f" - {meta['note']}" if meta.get("note") else ""
        meta_str = ""
        if meta.get("user_meta"):
            meta_str = " " + " ".join(f"{k}={v}" for k, v in meta["user_meta"].items())
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
                print(
                    f"  untracked files: {len(_list_tarball_members(dp['untracked_files']))} files"
                )

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
    """Synthesize empty snapshot metadata for a stamped (non-dev) version."""
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

    tool = tool or get_git_difftool(vcs)

    if tool:
        return _diff_with_external_tool(
            tool, vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
        )
    return _diff_real_tree(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2)


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
