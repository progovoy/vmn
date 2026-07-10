#!/usr/bin/env python3
"""Snapshot browsing for the vmn ui API (the ``snapshots/`` storage subdir)."""
from version_stamp.cli.snapshot import _resolve_verstr, get_snapshot_storage


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


def get_snapshot(root_path, app_name, verstr_ref):
    storage = snapshot_storage(root_path)
    verstr, err = _resolve_verstr(storage, app_name, verstr_ref, kind="snapshot")
    if err:
        return None, err
    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        return None, f"Snapshot {verstr} not found"
    return {
        "metadata": metadata,
        "patches": {
            k: bool(patches.get(k))
            for k in ("working_tree", "local_commits", "untracked_files")
        },
    }, None
