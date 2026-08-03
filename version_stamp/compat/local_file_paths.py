"""Compatibility for legacy verinfo/ directory layout.

Before snapshots, version files lived in ``verinfo/`` (and ``root_verinfo/``).
The new layout uses ``snapshots/`` (and ``root_snapshots/``). Read paths fall
back to the old directories.

Safe to remove when: no user has un-migrated ``verinfo/`` directories in their
``.vmn/`` tree (i.e., after ``create_snapshots`` has rewritten them all).
"""
import glob
import os

_SNAPSHOT_PATTERN = os.path.join("*", "metadata.yml")


def _find_snapshot_files(base_dir):
    return glob.glob(os.path.join(base_dir, _SNAPSHOT_PATTERN))


def _find_verinfo_files(base_dir):
    return glob.glob(os.path.join(base_dir, "*.yml"))


def resolve_with_verinfo_fallback(snap_dir, verinfo_dir):
    """Find the latest version file, checking snapshots/ first, then verinfo/.

    Returns the path to the latest file, or None.
    """
    snap_files = _find_snapshot_files(snap_dir)
    if snap_files:
        return max(snap_files, key=os.path.getmtime)

    verinfo_files = _find_verinfo_files(verinfo_dir)
    if verinfo_files:
        return max(verinfo_files, key=os.path.getmtime)

    return None


def resolve_specific_with_verinfo_fallback(snap_path, verinfo_path):
    """Find a specific version file, checking snapshots/ first, then verinfo/.

    Returns the path that exists, or None.
    """
    if os.path.isfile(snap_path):
        return snap_path
    if os.path.isfile(verinfo_path):
        return verinfo_path
    return None


def list_all_with_verinfo_fallback(snap_dir, verinfo_dir):
    """List all version files from both snapshots/ and verinfo/."""
    return _find_snapshot_files(snap_dir) + _find_verinfo_files(verinfo_dir)
