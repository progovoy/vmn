#!/usr/bin/env python3
"""Dev-version capture and restore: the building block behind experiments
and ``vmn goto -v <dev-version>``."""
import datetime

# The dev-version helpers live in version_stamp.devversion; the names below
# stay importable from here for experiment code.
from vmn_exp.core.resolve_ref import _resolve_verstr  # noqa: F401
from vmn_exp.core.storage_resolve import store_uri
from vmn_exp.core.writer import STORAGE_ENV, merge_conf_into_params
from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: F401
from vmn_exp.storage.open import open_storage  # noqa: F401
from version_stamp.api import (  # noqa: F401
    VMN_LOGGER,
    now_iso,
    # dev-version apply
    _apply_snapshot_patches,
    _reset_worktree,
    # dev-version capture
    _compute_diff_hash,
    _compute_verstr,
    _format_dev_verstr,
    _unique_snapshot_verstr,
    gather_create_data,
    # dev-version materialize
    _diff_real_tree,
    _diff_with_external_tool,
    _materialize_workdir,
    _strip_git_dirs,
    get_git_difftool,
    render_tree_diff,
    # dev-version untracked
    _untracked_caps,
)
from version_stamp.api import build_record_metadata as _build_snapshot_metadata
from version_stamp.api import patch_summary as _patch_summary  # noqa: F401


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
    """The checkout's snapshots, fronting the app's experiment store (flags,
    then ``VMN_EXPERIMENT_*``, then conf ``experiment.storage``)."""
    storage_params = {key: params.get(key) for key in STORAGE_ENV}
    merge_conf_into_params(vcs, storage_params)
    store = store_uri(storage_params, default_prefix="vmn-snapshots")
    return open_storage(store, vcs.vmn_root_path, subdir="snapshots")


def _save_safety_snapshot(vcs, params, target_verstr):
    """Snapshot the current dirty state before a restore overwrites it."""
    (
        base_version,
        commit_hash,
        patches,
        dirty_states,
        ver_info,
        err,
    ) = gather_create_data(vcs, allow_clean=True)
    if err is not None:
        return None
    diff_hash = _compute_diff_hash(patches)
    if diff_hash is None:
        return None

    storage = _get_storage(vcs, params)
    verstr = _unique_snapshot_verstr(
        storage, vcs.name, base_version, commit_hash, diff_hash
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
    """Apply a restore, first auto-snapshotting any dirty work it would clobber.
    *metadata* must come from ``load_code_record``, which refuses a record
    without usable code before anything is touched."""
    saved = _save_safety_snapshot(vcs, params, metadata.get("verstr"))
    if saved:
        VMN_LOGGER.info(
            f"Current work saved as {saved} — restore it anytime with: "
            f"vmn goto -v {saved} {vcs.name}"
        )
    if not params.get("deps_only"):
        _reset_worktree(vcs)
    return _apply_snapshot_patches(vcs, params, metadata, patches)
