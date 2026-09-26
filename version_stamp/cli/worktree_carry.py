"""`vmn wt create --carry-changes`: copy uncommitted work into an island."""
from version_stamp.cli.snapshot import copy_untracked_files
from version_stamp.cli.worktree_git import git_head, is_dirty, run_git
from version_stamp.core.logging import VMN_LOGGER


def carry_changes(source_path, dest_path):
    """Copy *source_path*'s uncommitted work into *dest_path*. False on failure.

    Tracked edits (staged or not) are applied as one patch; untracked,
    non-ignored files are copied. The source is left as it is. A checkout that
    does not sit on the source's commit is skipped, since the patch would not
    apply.
    """
    if not is_dirty(source_path):
        return True
    if git_head(source_path) != git_head(dest_path):
        VMN_LOGGER.warning(
            f"Not carrying changes from {source_path}: the island checkout is "
            "not at the same commit"
        )
        return True
    if not _apply_tracked_diff(source_path, dest_path):
        return False
    copy_untracked_files(source_path, dest_path)
    return True


def _apply_tracked_diff(source_path, dest_path):
    diff = run_git(source_path, ["diff", "--binary", "HEAD"])
    if diff is None or diff.returncode != 0:
        return False
    if not diff.stdout:
        return True
    applied = run_git(dest_path, ["apply", "--whitespace=nowarn"], stdin=diff.stdout)
    if applied is None or applied.returncode != 0:
        message = applied.stderr.strip() if applied else "git could not be run"
        VMN_LOGGER.error(f"Failed to carry tracked changes into {dest_path}: {message}")
        return False
    return True
