"""``vmn snapshot restore``: put a snapshot's tree back in the checkout.

The work it replaces is saved first, as a snapshot noted
``auto-saved before restore`` (unless it already is the target), and a hint
names the command that brings it back. The reset deletes untracked files, so a
restore that would lose ones over the snapshot size caps is refused unless
``params["force"]``. Then the worktree is reset to the snapshot's base commit
and its patches (and its deps') are applied — detached, as ``vmn goto`` does.

``params["deps_only"]`` leaves the app checkout alone and only applies deps.

Public: ``SAFETY_NOTE``, ``SNAPSHOT_HINT``,
``restore_record(vcs, params, stores, record, hint) -> int`` (the restore of an
already loaded ``(metadata, patches)``; ``vmn-exp restore`` and ``vmn goto -v
<dev>`` use it too, through ``version_stamp.api``),
``snapshot_restore(vcs, params, stores, verstr) -> int``.
"""
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.apply import _apply_snapshot_patches, _reset_worktree
from version_stamp.devversion.untracked import untracked_over_caps
from version_stamp.snapshot.capture import capture_identity
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


def restore_record(vcs, params, stores, record, hint):
    """Save the current work into *stores*, then put *record* in the checkout."""
    target = record[0].get("verstr")
    saved, err = _save_current_work(vcs, stores, target, params.get("force"))
    if err:
        return err
    if saved:
        VMN_LOGGER.info(
            f"Current work saved as {saved} — restore it anytime with: "
            + hint.format(app=vcs.name, verstr=saved)
        )
    if not params.get("deps_only") and _reset(vcs):
        return 1
    return _apply_snapshot_patches(vcs, params, *record)


def snapshot_restore(vcs, params, stores, verstr):
    record = load_snapshot(stores, vcs.name, verstr, "restore")
    if record is None:
        return 1
    ret = restore_record(vcs, params, stores, record, SNAPSHOT_HINT)
    if ret == 0:
        VMN_LOGGER.info(f"Restored snapshot {verstr}")
    return ret
