"""Materialize a snapshot into a complete working directory."""
import os
import shutil
import subprocess
import tempfile

import yaml

from version_stamp.core.git_cmd import git_stdout, run_git
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.apply import _apply_patches_to_workdir, dep_base_commit
from version_stamp.devversion.clone import (  # noqa: F401 (re-exported)
    _LOCAL_GIT_TIMEOUT_SEC,
    _NETWORK_GIT_TIMEOUT_SEC,
    _clone_at,
    _clone_local_at,
    _commit_exists,
    _git,
    _git_ok,
    _shallow_clone_at,
)
from version_stamp.devversion.untracked import copy_untracked_files
from version_stamp.snapshot.identity import safe_dep_name, safe_verstr


def _resolve_remote(remote, vcs):
    """Resolve a remote URL, converting relative paths to absolute."""
    if not remote:
        return remote
    vmn_root = vcs.vmn_root_path if vcs and hasattr(vcs, "vmn_root_path") else None
    if vmn_root and not remote.startswith(
        ("http://", "https://", "git://", "ssh://", "git@")
    ):
        resolved = os.path.normpath(os.path.join(vmn_root, remote))
        if os.path.exists(resolved):
            return resolved
    return remote


def _predates_untracked_capture(metadata):
    """A stored dev snapshot from before untracked files were captured."""
    return "has_untracked_files" not in metadata and "-dev." in str(
        metadata.get("verstr", "")
    )


def _strip_git_dirs(root_path):
    """Remove all .git directories to make export fully offline."""
    for dirpath, dirnames, _ in os.walk(root_path, topdown=True):
        if ".git" in dirnames:
            shutil.rmtree(os.path.join(dirpath, ".git"), ignore_errors=True)
            dirnames.remove(".git")


def _patches_failed(dest, patches, what):
    failed = _apply_patches_to_workdir(dest, patches)
    if failed:
        VMN_LOGGER.error(
            f"Failed to apply the patches of {what} ({', '.join(failed)}); "
            "refusing to materialize a partial tree"
        )
    return bool(failed)


def _materialize_workdir(vcs, metadata, patches, output_path):
    """Materialize a patch snapshot into a complete working directory."""
    base_commit = metadata.get("base_commit")
    remote = metadata.get("remote")

    if not base_commit:
        VMN_LOGGER.error("Snapshot metadata missing base_commit")
        return 1

    local_repo = getattr(vcs, "vmn_root_path", None) if vcs else None
    if not remote and not local_repo:
        VMN_LOGGER.error("Snapshot metadata missing remote URL")
        return 1

    err = _clone_at(
        output_path, local_repo, _resolve_remote(remote, vcs) or local_repo, base_commit
    )
    if err:
        return err

    if _patches_failed(output_path, patches, "the snapshot"):
        return 1

    if _predates_untracked_capture(metadata) and local_repo:
        try:
            current_head = git_stdout(vcs.vmn_root_path, ["rev-parse", "HEAD"]) or ""
            if current_head.startswith(base_commit[:7]) or base_commit.startswith(
                current_head[:7]
            ):
                copy_untracked_files(vcs.vmn_root_path, output_path)
            else:
                VMN_LOGGER.debug(
                    f"HEAD ({current_head[:7]}) != base_commit ({base_commit[:7]}), "
                    "skipping untracked files"
                )
        except Exception:
            VMN_LOGGER.debug("Failed to copy untracked files", exc_info=True)

    changesets = metadata.get("changesets", {})
    dep_patches = patches.get("deps", {})
    for dep_path, dep_info in changesets.items():
        if dep_path == ".":
            continue

        dep_hash = dep_base_commit(metadata, dep_path, dep_info)
        dep_remote = dep_info.get("remote")
        if not dep_hash or not dep_remote:
            VMN_LOGGER.warning(
                f"Dependency {dep_path} missing hash or remote, skipping"
            )
            continue

        dep_remote = _resolve_remote(dep_remote, vcs)
        dep_local = os.path.join(local_repo, dep_path) if local_repo else None

        dep_dest = os.path.join(output_path, dep_path)
        err = _clone_at(dep_dest, dep_local, dep_remote, dep_hash)
        if err:
            VMN_LOGGER.warning(f"Failed to export dependency {dep_path}")
            continue

        dp = dep_patches.get(safe_dep_name(dep_path)) or dep_patches.get(dep_path)
        if dp and _patches_failed(dep_dest, dp, f"dependency {dep_path}"):
            return 1

    meta_path = os.path.join(output_path, "vmn_metadata.yml")
    with open(meta_path, "w") as f:
        yaml.dump(metadata, f, sort_keys=True)

    return 0


def get_git_difftool(vcs):
    try:
        return vcs.backend._be.git.config("diff.tool")
    except Exception:
        return None


def _materialize_for_diff(vcs, verstr, meta, patches, dest):
    """Materialize a snapshot/experiment into ``dest`` (no .git, no vmn metadata)
    for diffing. 'current'/base-less meta materializes the live HEAD.
    """
    m = dict(meta)
    if not m.get("base_commit"):
        m["base_commit"] = vcs.backend.changeset()
    if _materialize_workdir(vcs, m, patches, dest) != 0:
        return False
    _strip_git_dirs(dest)
    try:
        os.remove(os.path.join(dest, "vmn_metadata.yml"))
    except OSError:
        pass
    return True


def _materialize_pair(vcs, parent, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Materialize both sides into distinct dirs under *parent*; their names
    (relative to *parent*), or None when either side failed."""
    name1 = safe_verstr(verstr1)
    name2 = safe_verstr(verstr2)
    if name1 == name2:
        name2 += "_b"
    for verstr, meta, patches, name in (
        (verstr1, meta1, patches1, name1),
        (verstr2, meta2, patches2, name2),
    ):
        if not _materialize_for_diff(
            vcs, verstr, meta, patches, os.path.join(parent, name)
        ):
            return None
    return name1, name2


def render_tree_diff(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Real file-level diff text between two materialized snapshot workdirs.

    Returns (diff_text, error_message_or_None); empty text means identical.
    """
    parent = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        names = _materialize_pair(
            vcs, parent, verstr1, meta1, patches1, verstr2, meta2, patches2
        )
        if names is None:
            return None, "Failed to materialize snapshots for diff"
        result = run_git(parent, ["diff", "--no-index", "--", *names], text=True)
        if result is None:
            return None, "git diff could not be run"
        if result.returncode > 1:
            return None, f"git diff failed: {result.stderr.strip()}"
        return result.stdout, None
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _diff_real_tree(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Print a real file-level diff between two materialized snapshot workdirs."""
    text, err = render_tree_diff(
        vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
    )
    if err:
        VMN_LOGGER.error(err)
        return 1
    if text.strip():
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        print(f"{verstr1} and {verstr2} are identical")
    return 0


def _diff_with_external_tool(
    tool, vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
):
    """Materialize both snapshots as workdirs and launch external diff tool."""
    tmpdir = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        names = _materialize_pair(
            vcs, tmpdir, verstr1, meta1, patches1, verstr2, meta2, patches2
        )
        if names is None:
            VMN_LOGGER.error("Failed to materialize snapshots for diff")
            return 1
        left_dir, right_dir = (os.path.join(tmpdir, name) for name in names)
        result = subprocess.run([tool, left_dir, right_dir])
        return result.returncode
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
