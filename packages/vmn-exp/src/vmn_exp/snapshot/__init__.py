#!/usr/bin/env python3
"""Dev-version capture and restore: the building block behind experiments
and ``vmn goto -v <dev-version>``."""
import datetime

# The storage backends and the dev-version helpers live in their own modules;
# these names stay importable from here for experiment code.
from vmn_exp.core.resolve_ref import _resolve_verstr  # noqa: F401
from vmn_exp.storage.cached import (  # noqa: F401
    CachedSnapshotStorage,
    get_snapshot_storage,
)
from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: F401
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: F401
from version_stamp.api import (  # noqa: F401
    VMN_LOGGER,
    now_iso,
    # dev-version apply
    _apply_patches_to_workdir,
    _apply_snapshot_patches,
    _reset_worktree,
    # dev-version capture
    _compute_diff_hash,
    _compute_verstr,
    _format_dev_verstr,
    _generate_dep_patches,
    _generate_patches,
    _unique_snapshot_verstr,
    gather_create_data,
    # dev-version materialize
    _diff_real_tree,
    _diff_with_external_tool,
    _materialize_workdir,
    _shallow_clone_at,
    _strip_git_dirs,
    get_git_difftool,
    render_tree_diff,
    # dev-version untracked
    _collect_untracked_tarball,
    _hash_untracked_content,
    _untracked_caps,
    copy_untracked_files,
    payload_from_tarball,
)


def untracked_payload(repo_path):
    """devversion's ``untracked_payload``, collecting through this module's
    ``_collect_untracked_tarball`` so experiment code (and its tests) can
    still patch the collector here."""
    return payload_from_tarball(*_collect_untracked_tarball(repo_path))


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
        "timestamp": now_iso(),
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
            f"vmn goto -v {saved} {vcs.name}"
        )
    if not params.get("deps_only"):
        _reset_worktree(vcs)
    return _apply_snapshot_patches(vcs, params, metadata, patches)
