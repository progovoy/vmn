"""``vmn snapshot diff``: a snapshot's tree against another tree.

The other side (``to``) is the current working state by default (or
``current``), else a snapshot ref (verstr, prefix, ``@N``, ``latest``) or a
stamped version. Both sides are materialized and compared file by file
(``git diff --no-index``), or handed to *tool* — default: git's
``diff.tool`` — as two directories.

Public: ``CURRENT``, ``snapshot_diff(vcs, stores, verstr, to=None, tool=None) -> int``.
"""
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.capture import gather_create_data
from version_stamp.devversion.materialize import (
    _diff_real_tree,
    _diff_with_external_tool,
    get_git_difftool,
)
from version_stamp.snapshot.load import load_snapshot, stamped_state
from version_stamp.snapshot.refs import resolve_snapshot_ref

CURRENT = "current"


def _current_state(vcs):
    """The working state as a snapshot would record it, patches included."""
    _, commit_hash, patches, _, ver_info, err = gather_create_data(vcs)
    if err is not None:
        return None
    metadata = {
        "verstr": CURRENT,
        "base_commit": commit_hash,
        "changesets": ver_info["stamping"]["app"].get("changesets", {}),
    }
    return metadata, patches


def _side(vcs, stores, ref):
    """``(verstr, metadata, patches)`` of a snapshot or stamped version, or None."""
    verstr, err = resolve_snapshot_ref(stores.records, vcs.name, ref)
    if err:
        VMN_LOGGER.error(err)
        return None
    if stores.records.exists(vcs.name, verstr):
        record = load_snapshot(stores, vcs.name, verstr, "diff")
    else:
        record = stamped_state(vcs, verstr)
        if record is None:
            VMN_LOGGER.error(f"No snapshot or stamped version {verstr} of {vcs.name}")
    return None if record is None else (verstr, *record)


def _other_side(vcs, stores, to):
    if to in (None, CURRENT):
        state = _current_state(vcs)
        return None if state is None else (CURRENT, *state)
    return _side(vcs, stores, to)


def snapshot_diff(vcs, stores, verstr, to=None, tool=None):
    left = _side(vcs, stores, verstr)
    right = left and _other_side(vcs, stores, to)
    if not right:
        return 1
    tool = tool or get_git_difftool(vcs)
    if tool:
        return _diff_with_external_tool(tool, vcs, *left, *right)
    return _diff_real_tree(vcs, *left, *right)
