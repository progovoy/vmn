#!/usr/bin/env python3
"""Snapshot browsing for the vmn ui API (the ``snapshots/`` storage subdir)."""

from version_stamp.cli.snapshot import _resolve_verstr, get_snapshot_storage

# Patch kind -> the metadata flag recording whether the snapshot holds it.
_PATCH_FLAGS = {
    "working_tree": "has_working_tree_patch",
    "local_commits": "has_local_commits_patch",
    "untracked_files": "has_untracked_files",
}


def snapshot_storage(root_path):
    return get_snapshot_storage("local", vmn_root_path=root_path)


def list_snapshots(root_path, app_name):
    rows = snapshot_storage(root_path).list_snapshots(app_name)
    return [
        {
            "verstr": m["verstr"],
            "timestamp": m.get("timestamp"),
            "note": m.get("note"),
            "branch": m.get("branch"),
            "base_version": m.get("base_version"),
            "user_meta": m.get("user_meta"),
            "dirty_states": m.get("dirty_states"),
        }
        for m in rows
    ]


def _load_metadata(storage, app_name, verstr):
    return storage.load_metadata(app_name, verstr)


def _patch_presence(storage, app_name, verstr, metadata):
    """Which patch kinds a snapshot holds — from its metadata flags.

    Only a legacy record that predates the flags pays for loading the patches
    (the untracked tarball can be hundreds of MB).
    """
    if all(flag in metadata for flag in _PATCH_FLAGS.values()):
        return {kind: bool(metadata[flag]) for kind, flag in _PATCH_FLAGS.items()}
    _, patches = storage.load(app_name, verstr)
    return {kind: bool((patches or {}).get(kind)) for kind in _PATCH_FLAGS}


def get_snapshot(root_path, app_name, verstr_ref):
    storage = snapshot_storage(root_path)
    verstr, err = _resolve_verstr(storage, app_name, verstr_ref, kind="snapshot")
    if err:
        return None, err
    metadata = _load_metadata(storage, app_name, verstr)
    if metadata is None:
        return None, f"Snapshot {verstr} not found"
    return {
        "metadata": metadata,
        "patches": _patch_presence(storage, app_name, verstr, metadata),
    }, None
