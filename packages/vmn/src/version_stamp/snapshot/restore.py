"""``vmn snapshot restore``: put a snapshot's tree back in the checkout.

The work it replaces is saved first, as a snapshot noted
``auto-saved before restore`` (unless it already is the target), and a hint
names the command that brings it back. The reset deletes untracked files, so a
restore that would lose ones over the snapshot size caps is refused unless
``params["force"]``. Then the worktree is reset to the snapshot's base commit
and its patches (and its deps') are applied — detached, as ``vmn goto`` does.

Public: ``SAFETY_NOTE``,
``snapshot_restore(vcs, params, stores, verstr) -> int``.
"""
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.apply import _apply_snapshot_patches, _reset_worktree
from version_stamp.devversion.untracked import untracked_over_caps
from version_stamp.snapshot.capture import capture_identity
from version_stamp.snapshot.create import snapshot_verstr, store_snapshot
from version_stamp.snapshot.load import load_snapshot

SAFETY_NOTE = "auto-saved before restore"


def _refuse_dropping(dropped):
    VMN_LOGGER.error(
        "Restoring would delete untracked files the safety snapshot cannot hold "
        f"(over the size caps): {', '.join(dropped)}. Move them away, raise "
        "VMN_SNAPSHOT_MAX_FILE_MB / VMN_SNAPSHOT_MAX_TOTAL_MB, or pass --force "
        "to restore anyway and lose them."
    )
    return 1


def _save_current_work(vcs, stores, target, force):
    """``(saved verstr or None, error code or None)``."""
    captured, err = capture_identity(vcs)
    if err is not None:
        return None, err
    if not captured.diff_hash:
        return None, None
    dropped = [] if force else untracked_over_caps(vcs.vmn_root_path)
    if dropped:
        return None, _refuse_dropping(dropped)
    verstr = snapshot_verstr(stores.records, vcs.name, captured)
    if verstr == target:
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


def snapshot_restore(vcs, params, stores, verstr):
    record = load_snapshot(stores, vcs.name, verstr, "restore")
    if record is None:
        return 1
    saved, err = _save_current_work(vcs, stores, verstr, params.get("force"))
    if err:
        return err
    if saved:
        VMN_LOGGER.info(
            f"Current work saved as {saved} — restore it anytime with: "
            f"vmn snapshot restore {vcs.name} -v {saved}"
        )
    if _reset(vcs):
        return 1
    ret = _apply_snapshot_patches(vcs, params, *record)
    if ret == 0:
        VMN_LOGGER.info(f"Restored snapshot {verstr}")
    return ret
