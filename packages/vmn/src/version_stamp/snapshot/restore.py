"""``vmn snapshot restore``: put a snapshot's tree back in the checkout.

The work it replaces is saved first, as a snapshot noted
``auto-saved before restore`` (unless it already is the target), and a hint
names the command that brings it back. The resets (of the app and of each
configured dep) delete untracked files, so a restore that would lose ones over
the snapshot size caps is refused unless ``params["force"]``. Then the worktree is reset to the snapshot's base commit
and its patches are applied — detached, as ``vmn goto`` does; each recorded
dep is reset, checked out at its base commit (``dep_base_commits``, else its
changeset hash) and patched. A base commit
missing from the repo fails before anything is touched; any step that does not
apply makes the restore fail.

``params["deps_only"]`` leaves the app checkout alone and only applies deps.

Public: ``SAFETY_NOTE``, ``SNAPSHOT_HINT``,
``restore_record(vcs, params, stores, record, hint) -> int`` (the restore of an
already loaded ``(metadata, patches)``; ``vmn-exp restore`` and ``vmn goto -v
<dev>`` use it too, through ``version_stamp.api``),
``snapshot_restore(vcs, params, stores, verstr) -> int``.
"""
import os

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.apply import _apply_snapshot_patches, _reset_worktree
from version_stamp.devversion.clone import _commit_exists
from version_stamp.devversion.untracked import untracked_over_caps
from version_stamp.snapshot.capture import _repos_with_untracked, capture_identity
from version_stamp.snapshot.create import snapshot_verstr, store_snapshot
from version_stamp.snapshot.load import load_snapshot

SAFETY_NOTE = "auto-saved before restore"
# How the saved work is brought back, formatted with ``app`` and ``verstr``.
SNAPSHOT_HINT = "vmn snapshot restore {app} -v {verstr}"


def _refuse_dropping(dropped):
    VMN_LOGGER.error(
        "Restoring would delete untracked files the safety snapshot cannot hold "
        f"(over the size caps): {', '.join(dropped)}. Move them away, raise "
        "VMN_SNAPSHOT_MAX_FILE_MB / VMN_SNAPSHOT_MAX_TOTAL_MB, or pass --force "
        "to restore anyway and lose them."
    )
    return 1


def _reset_deps(vcs, metadata):
    """The configured deps with a checkout that restoring *metadata* resets."""
    return [
        dep_path
        for dep_path in metadata.get("changesets") or {}
        if dep_path != "." and dep_path in vcs.configured_deps
        and os.path.isdir(os.path.join(vcs.vmn_root_path, dep_path))
    ]


def _dropped_untracked(vcs, identity, reset_deps):
    """Untracked paths the resets would delete that a snapshot cannot hold
    (only the repos *identity* saw untracked files in are scanned)."""
    repos = _repos_with_untracked(vcs, identity)
    dropped = untracked_over_caps(vcs.vmn_root_path) if None in repos else []
    for dep_path in reset_deps:
        if dep_path in repos:
            dropped.extend(f"{dep_path}/{p}" for p in untracked_over_caps(repos[dep_path]))
    return dropped


def _save_current_work(vcs, stores, metadata, reset_deps, force):
    """``(saved verstr or None, error code or None)``."""
    captured, err = capture_identity(vcs)
    if err is not None:
        return None, err
    if not captured.diff_hash:
        return None, None
    dropped = [] if force else _dropped_untracked(vcs, captured.identity, reset_deps)
    if dropped:
        return None, _refuse_dropping(dropped)
    verstr = snapshot_verstr(stores.records, vcs.name, captured)
    if verstr == metadata.get("verstr"):
        return None, None
    store_snapshot(vcs, stores, captured, verstr, note=SAFETY_NOTE)
    return verstr, None


def _reset(vcs):
    try:
        _reset_worktree(vcs)
    except RuntimeError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    return 0


def _base_commit_missing(vcs, metadata):
    base_commit = metadata.get("base_commit")
    if _commit_exists(vcs.vmn_root_path, base_commit):
        return False
    VMN_LOGGER.error(
        f"Base commit {str(base_commit)[:7]} of {metadata.get('verstr')} is not "
        "in the local repository; fetch it (git fetch) and retry. Nothing was changed."
    )
    return True


def restore_record(vcs, params, stores, record, hint):
    """Save the current work into *stores*, then put *record* in the checkout."""
    if not params.get("deps_only") and _base_commit_missing(vcs, record[0]):
        return 1
    reset_deps = _reset_deps(vcs, record[0])
    saved, err = _save_current_work(vcs, stores, record[0], reset_deps, params.get("force"))
    if err:
        return err
    if saved:
        VMN_LOGGER.info(
            f"Current work saved as {saved} — restore it anytime with: "
            + hint.format(app=vcs.name, verstr=saved)
        )
    if not params.get("deps_only") and _reset(vcs):
        return 1
    return _apply_snapshot_patches(vcs, params, *record, reset_deps)


def snapshot_restore(vcs, params, stores, verstr):
    record = load_snapshot(stores, vcs.name, verstr, "restore")
    if record is None:
        return 1
    ret = restore_record(vcs, params, stores, record, SNAPSHOT_HINT)
    if ret == 0:
        VMN_LOGGER.info(f"Restored snapshot {verstr}")
    return ret
