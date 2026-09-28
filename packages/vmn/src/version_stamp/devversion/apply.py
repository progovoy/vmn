"""Apply snapshot patches to a working tree."""
import os
import subprocess

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.untracked import (
    _ensure_trailing_newline,
    _extract_untracked_tarball,
)


def _apply_patches_to_workdir(dest, patches):
    """Apply local_commits and working_tree patches to a workdir."""
    if patches.get("local_commits"):
        result = subprocess.run(
            ["git", "am", "--3way"],
            input=_ensure_trailing_newline(patches["local_commits"]),
            capture_output=True,
            text=True,
            cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply local commits: {result.stderr}")

    if patches.get("working_tree"):
        result = subprocess.run(
            ["git", "apply"],
            input=_ensure_trailing_newline(patches["working_tree"]),
            capture_output=True,
            text=True,
            cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply working tree patch: {result.stderr}")

    if patches.get("untracked_files"):
        try:
            _extract_untracked_tarball(dest, patches["untracked_files"])
        except Exception:
            VMN_LOGGER.debug(
                "Failed to extract untracked files in workdir", exc_info=True
            )


def _apply_dep_patches(vcs, metadata, patches):
    dep_patches = patches.get("deps", {})
    if not dep_patches:
        return

    changesets = metadata.get("changesets", {})
    for dep_name, dp in dep_patches.items():
        dep_info = None
        for cs_path, cs_info in changesets.items():
            safe = cs_path.replace(os.sep, "_").replace("/", "_")
            if safe == dep_name or cs_path == dep_name:
                dep_info = cs_info
                dep_path = cs_path
                break

        if not dep_info:
            VMN_LOGGER.warning(
                f"No changeset info for dep {dep_name}, skipping patches"
            )
            continue

        full_path = os.path.join(vcs.vmn_root_path, dep_path)
        if not os.path.isdir(full_path):
            VMN_LOGGER.warning(f"Dep directory {dep_path} not found, skipping patches")
            continue

        dep_hash = dep_info.get("hash")
        if dep_hash:
            try:
                result = subprocess.run(
                    ["git", "checkout", dep_hash],
                    capture_output=True,
                    text=True,
                    cwd=full_path,
                )
                if result.returncode != 0:
                    VMN_LOGGER.warning(
                        f"Failed to checkout dep {dep_path} at {dep_hash[:7]}"
                    )
            except Exception:
                VMN_LOGGER.debug(f"Failed to checkout dep {dep_path}", exc_info=True)

        _apply_patches_to_workdir(full_path, dp)


def _apply_snapshot_patches(vcs, params, metadata, patches):
    """Apply snapshot patches to restore a dev version state."""
    base_commit = metadata["base_commit"]

    if not params.get("deps_only"):
        try:
            vcs.backend.checkout(rev=base_commit)
        except Exception:
            VMN_LOGGER.error(f"Failed to checkout base commit {base_commit[:7]}")
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
            return 1

        if patches.get("local_commits"):
            result = subprocess.run(
                ["git", "am", "--3way"],
                input=_ensure_trailing_newline(patches["local_commits"]),
                capture_output=True,
                text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply local commits patch: {result.stderr}"
                )
                return 1

        if patches.get("working_tree"):
            result = subprocess.run(
                ["git", "apply", "--3way"],
                input=_ensure_trailing_newline(patches["working_tree"]),
                capture_output=True,
                text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(f"Failed to apply working tree patch: {result.stderr}")
                return 1

        if patches.get("untracked_files"):
            try:
                _extract_untracked_tarball(
                    vcs.vmn_root_path, patches["untracked_files"]
                )
            except Exception:
                VMN_LOGGER.warning("Failed to extract untracked files from snapshot")
                VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

    _apply_dep_patches(vcs, metadata, patches)

    VMN_LOGGER.info(f"Restored dev version {metadata['verstr']} of {vcs.name}")
    return 0


def _reset_worktree(vcs):
    """Discard tracked + untracked working-tree changes (keeps .vmn/ ignored data)."""
    for cmd in (["git", "reset", "--hard"], ["git", "clean", "-fd"]):
        result = subprocess.run(cmd, cwd=vcs.vmn_root_path, capture_output=True)
        if result.returncode != 0:
            stderr = (
                result.stderr.decode().strip() if result.stderr else "unknown error"
            )
            raise RuntimeError(
                f"Failed to reset working tree ({' '.join(cmd)}): {stderr}"
            )
