#!/usr/bin/env python3
"""Creating an experiment record from an exported snapshot — no git needed.

``vmn snapshot export`` writes a ``vmn_metadata.yml`` next to the code it
exports; a container built from that tree can record experiments against it.
Both ``vmn exp create/run --from-snapshot`` and ``version_stamp.exp.start_run``
do, so the record is shaped here in core rather than in either entry point.
"""
import os

import yaml

from version_stamp.core.experiment_writer import create_run
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import now_iso

SNAPSHOT_METADATA_FILE = "vmn_metadata.yml"


def _load_snapshot_meta(snapshot_meta_path):
    """The exported snapshot's metadata dict, or None (logged) when unusable."""
    if os.path.isdir(snapshot_meta_path):
        snapshot_meta_path = os.path.join(snapshot_meta_path, SNAPSHOT_METADATA_FILE)
    if not os.path.isfile(snapshot_meta_path):
        VMN_LOGGER.error("Snapshot metadata not found: " + snapshot_meta_path)
        return None

    with open(snapshot_meta_path) as f:
        snap_meta = yaml.safe_load(f)

    if not isinstance(snap_meta, dict) or "verstr" not in snap_meta:
        VMN_LOGGER.error(
            "Invalid snapshot metadata (missing verstr): " + snapshot_meta_path
        )
        return None
    return snap_meta


def _record_template(snap_meta, app, note):
    """The new run's metadata, minus the identity create_run stamps on it."""
    template = {
        "base_version": snap_meta.get("base_version"),
        "base_commit": snap_meta.get("base_commit"),
        "branch": snap_meta.get("branch"),
        "remote": snap_meta.get("remote"),
        "timestamp": now_iso(),
        "note": note,
        "app_name": app,
        "from_snapshot": True,
        "dirty_states": snap_meta.get("dirty_states", []),
        "has_working_tree_patch": False,
        "has_local_commits_patch": False,
        "has_untracked_files": False,
        "has_dep_patches": False,
    }
    if snap_meta.get("changesets"):
        template["changesets"] = snap_meta["changesets"]
    return template


def create_from_snapshot(
    storage,
    app_name,
    snapshot_meta_path,
    note=None,
    extra_create_data=None,
    parent=None,
    name=None,
):
    """Create an experiment from an exported snapshot directory or metadata file.

    Returns ``(verstr, error_code)``; *error_code* is None on success.
    """
    snap_meta = _load_snapshot_meta(snapshot_meta_path)
    if snap_meta is None:
        return None, 1

    app = app_name or snap_meta.get("app_name")
    if not app:
        VMN_LOGGER.error(
            "App name not found in snapshot metadata and not provided via CLI"
        )
        return None, 1

    # Allocation creates the record: the name is claimed atomically, so two
    # hosts sharing a bucket or directory never end up with the same run.
    verstr = create_run(
        storage,
        app,
        snap_meta["verstr"],
        _record_template(snap_meta, app, note),
        {},
        note=note,
        create_data=extra_create_data,
        parent=parent,
        name=name,
    )
    return verstr, None
