"""Apply snapshot patches to a working tree."""
import os
import subprocess

from version_stamp.core.constants import VMN_USER_NAME
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.untracked import (
    _ensure_trailing_newline,
    _extract_untracked_tarball,
)


def _apply_patches_to_workdir(dest, patches, three_way=False):
    """Apply local_commits, working_tree and untracked_files patches to a
    workdir; the names of the steps that failed (empty when all applied).
    *three_way* lets the working-tree patch fall back to a 3-way merge."""
    steps = (
        ("local_commits", _git_am),
        ("working_tree", _git_apply_3way if three_way else _git_apply),
        ("untracked_files", _extract_untracked),
    )
    return [
        name
        for name, apply in steps
        if patches.get(name) and not apply(dest, patches[name])
    ]


def _git_am(dest, patch):
    cmd = ["git", *_fallback_identity(dest), "am", "--3way"]
    if _run_with_patch(cmd, patch, dest, "local commits"):
        return True
    subprocess.run(["git", "am", "--abort"], capture_output=True, cwd=dest)
    return False


def _fallback_identity(dest):
    """``-c user.*`` options for a repo that has no committer identity."""
    probe = subprocess.run(
        ["git", "var", "GIT_COMMITTER_IDENT"], capture_output=True, cwd=dest
    )
    if probe.returncode == 0:
        return []
    return ["-c", f"user.name={VMN_USER_NAME}", "-c", f"user.email={VMN_USER_NAME}"]


def _git_apply(dest, patch):
    return _run_with_patch(["git", "apply"], patch, dest, "working tree patch")


def _git_apply_3way(dest, patch):
    cmd = ["git", "apply", "--3way"]
    return _run_with_patch(cmd, patch, dest, "working tree patch")


def _run_with_patch(cmd, patch, cwd, what):
    """Run *cmd* on *patch*; whether it applied (a warning when not)."""
    result = subprocess.run(
        cmd,
        input=_ensure_trailing_newline(patch),
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        VMN_LOGGER.warning(f"Failed to apply {what}: {result.stderr}")
    return result.returncode == 0


def _extract_untracked(dest, tarball):
    try:
        _extract_untracked_tarball(dest, tarball)
    except Exception:
        VMN_LOGGER.warning("Failed to extract untracked files in workdir")
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
        return False
    return True


def _dep_patches_of(patches, dep_path):
    dep_patches = patches.get("deps", {})
    safe = dep_path.replace(os.sep, "_").replace("/", "_")
    return dep_patches.get(safe) or dep_patches.get(dep_path) or {}


def dep_base_commit(metadata, dep_path, dep_info):
    """The commit *dep_path*'s patches apply to: the one captured with them
    (``dep_base_commits``), else — older records — its changeset hash."""
    captured = (metadata.get("dep_base_commits") or {}).get(dep_path)
    return captured or (dep_info or {}).get("hash")


def _checkout_dep(vcs, dep_path, dep_hash):
    """Put the dep checkout at *dep_hash* (detached); whether it worked.

    A configured dep's work was saved by the restore's safety snapshot, so
    it is discarded first."""
    full_path = os.path.join(vcs.vmn_root_path, dep_path)
    try:
        if dep_path in (getattr(vcs, "configured_deps", None) or {}):
            _reset_repo(full_path)
    except RuntimeError as exc:
        VMN_LOGGER.error(f"Dep {dep_path}: {exc}")
        return False
    result = subprocess.run(
        ["git", "checkout", "--quiet", "--detach", dep_hash],
        capture_output=True,
        text=True,
        cwd=full_path,
    )
    if result.returncode != 0:
        VMN_LOGGER.error(
            f"Failed to checkout dep {dep_path} at {dep_hash[:7]}: {result.stderr}"
        )
    return result.returncode == 0


def _restore_dep(vcs, dep_path, dep_hash, patches):
    """Whether *dep_path* was restored (a missing checkout is skipped)."""
    if not os.path.isdir(os.path.join(vcs.vmn_root_path, dep_path)):
        VMN_LOGGER.warning(f"Dep directory {dep_path} not found, skipping")
        return True
    if dep_hash and not _checkout_dep(vcs, dep_path, dep_hash):
        return False
    full_path = os.path.join(vcs.vmn_root_path, dep_path)
    failed = _apply_patches_to_workdir(
        full_path, _dep_patches_of(patches, dep_path), three_way=True
    )
    if failed:
        VMN_LOGGER.error(f"Failed to restore dep {dep_path}: {', '.join(failed)}")
    return not failed


def _apply_dep_patches(vcs, metadata, patches):
    """Check every recorded dep out at its base commit and apply its patches;
    the paths of the deps that could not be restored."""
    changesets = metadata.get("changesets") or {}
    return [
        dep_path
        for dep_path, dep_info in changesets.items()
        if dep_path != "."
        and not _restore_dep(
            vcs, dep_path, dep_base_commit(metadata, dep_path, dep_info), patches
        )
    ]


def _restore_app(vcs, metadata, patches):
    base_commit = metadata["base_commit"]
    try:
        vcs.backend.checkout(rev=base_commit)
    except Exception:
        VMN_LOGGER.error(f"Failed to checkout base commit {base_commit[:7]}")
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
        return False
    failed = _apply_patches_to_workdir(vcs.vmn_root_path, patches, three_way=True)
    if failed:
        VMN_LOGGER.error(f"Failed to apply snapshot patches: {', '.join(failed)}")
    return not failed


def _apply_snapshot_patches(vcs, params, metadata, patches):
    """Apply snapshot patches to restore a dev version state."""
    if not params.get("deps_only") and not _restore_app(vcs, metadata, patches):
        return 1
    if _apply_dep_patches(vcs, metadata, patches):
        return 1

    VMN_LOGGER.info(f"Restored dev version {metadata['verstr']} of {vcs.name}")
    return 0


def _reset_repo(repo_path):
    """Discard tracked + untracked working-tree changes (keeps ignored data)."""
    for cmd in (["git", "reset", "--hard"], ["git", "clean", "-fd"]):
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True)
        if result.returncode != 0:
            stderr = (
                result.stderr.decode().strip() if result.stderr else "unknown error"
            )
            raise RuntimeError(
                f"Failed to reset working tree ({' '.join(cmd)}): {stderr}"
            )


def _reset_worktree(vcs):
    """Discard tracked + untracked working-tree changes (keeps .vmn/ ignored data)."""
    _reset_repo(vcs.vmn_root_path)
