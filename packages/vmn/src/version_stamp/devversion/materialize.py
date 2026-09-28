"""Materialize a snapshot into a complete working directory."""
import os
import shutil
import subprocess
import tempfile

import yaml

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.apply import _apply_patches_to_workdir
from version_stamp.devversion.untracked import copy_untracked_files

# Seconds a git subprocess may take while materializing a snapshot: local
# operations are quick, network ones must not hang an export or a ui diff.
_LOCAL_GIT_TIMEOUT_SEC = 120
_NETWORK_GIT_TIMEOUT_SEC = 300


def _git(args, cwd=None, timeout=_LOCAL_GIT_TIMEOUT_SEC):
    """Run git; a CompletedProcess, or None when it timed out."""
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        VMN_LOGGER.error(f"git {' '.join(args[:2])} timed out after {timeout}s")
        return None


def _git_ok(args, cwd=None, timeout=_LOCAL_GIT_TIMEOUT_SEC, what=None):
    result = _git(args, cwd=cwd, timeout=timeout)
    if result is not None and result.returncode == 0:
        return True
    if what and result is not None:
        VMN_LOGGER.error(f"{what} failed: {result.stderr}")
    return False


def _commit_exists(repo_path, commit_hash):
    """Whether *commit_hash* is in the local repository at *repo_path*."""
    if not repo_path or not commit_hash or not os.path.isdir(repo_path):
        return False
    return _git_ok(["cat-file", "-e", f"{commit_hash}^{{commit}}"], cwd=repo_path)


def _clone_local_at(dest, repo_path, commit_hash):
    """Check *commit_hash* out of a local repository — no network involved."""
    if not _git_ok(
        ["clone", "--shared", "--no-checkout", "--quiet", repo_path, dest],
        what="git clone (local)",
    ):
        return 1
    if not _git_ok(
        ["checkout", "--quiet", commit_hash],
        cwd=dest,
        what=f"git checkout {commit_hash[:7]}",
    ):
        return 1
    return 0


def _shallow_clone_at(dest, remote, commit_hash):
    """Create a shallow clone at a specific commit."""
    os.makedirs(dest, exist_ok=True)
    if not _git_ok(["init"], cwd=dest, what=f"git init in {dest}"):
        return 1

    if _git_ok(
        ["fetch", "--depth", "1", remote, commit_hash],
        cwd=dest,
        timeout=_NETWORK_GIT_TIMEOUT_SEC,
    ) and _git_ok(["checkout", "FETCH_HEAD"], cwd=dest):
        return 0

    VMN_LOGGER.warning(
        f"Shallow fetch failed for {commit_hash[:7]}, falling back to full clone"
    )
    shutil.rmtree(dest, ignore_errors=True)
    if not _git_ok(
        ["clone", "--no-checkout", remote, dest],
        timeout=_NETWORK_GIT_TIMEOUT_SEC,
        what="git clone",
    ):
        return 1

    if not _git_ok(
        ["checkout", commit_hash], cwd=dest, what=f"git checkout {commit_hash[:7]}"
    ):
        return 1

    return 0


def _clone_at(dest, local_repo, remote, commit_hash):
    """Materialize *commit_hash* from the local repo when it has it, else remote."""
    if _commit_exists(local_repo, commit_hash):
        return _clone_local_at(dest, local_repo, commit_hash)
    return _shallow_clone_at(dest, remote, commit_hash)


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

    _apply_patches_to_workdir(output_path, patches)

    if _predates_untracked_capture(metadata) and local_repo:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=vcs.vmn_root_path,
            )
            current_head = result.stdout.strip()
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

        dep_hash = dep_info.get("hash")
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

        safe_dep = dep_path.replace(os.sep, "_").replace("/", "_")
        dp = dep_patches.get(safe_dep) or dep_patches.get(dep_path)
        if dp:
            _apply_patches_to_workdir(dep_dest, dp)

    meta_path = os.path.join(output_path, "vmn_metadata.yml")
    with open(meta_path, "w") as f:
        yaml.dump(metadata, f, sort_keys=True)

    return 0


def _write_snapshot_to_dir(directory, metadata, patches):
    """Write snapshot metadata and patches to a directory (fallback)."""
    with open(os.path.join(directory, "metadata.yml"), "w") as f:
        yaml.dump(metadata, f, sort_keys=True)
    if patches.get("working_tree"):
        with open(os.path.join(directory, "working_tree.patch"), "w") as f:
            f.write(patches["working_tree"])
    if patches.get("local_commits"):
        with open(os.path.join(directory, "local_commits.patch"), "w") as f:
            f.write(patches["local_commits"])
    if patches.get("untracked_files"):
        with open(os.path.join(directory, "untracked_files.tar.gz"), "wb") as f:
            f.write(patches["untracked_files"])


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


def render_tree_diff(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Real file-level diff text between two materialized snapshot workdirs.

    Returns (diff_text, error_message_or_None); empty text means identical.
    """
    parent = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        name1 = verstr1.replace("+", "_plus_")
        name2 = verstr2.replace("+", "_plus_")
        if name1 == name2:
            name2 += "_b"
        ok1 = _materialize_for_diff(
            vcs, verstr1, meta1, patches1, os.path.join(parent, name1)
        )
        ok2 = _materialize_for_diff(
            vcs, verstr2, meta2, patches2, os.path.join(parent, name2)
        )
        if not ok1 or not ok2:
            return None, "Failed to materialize snapshots for diff"
        result = subprocess.run(
            ["git", "diff", "--no-index", "--", name1, name2],
            capture_output=True,
            text=True,
            cwd=parent,
        )
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
        left_dir = os.path.join(tmpdir, verstr1.replace("+", "_plus_"))
        right_dir = os.path.join(tmpdir, verstr2.replace("+", "_plus_"))

        left_ok = _materialize_workdir(vcs, meta1, patches1, left_dir) == 0
        right_ok = _materialize_workdir(vcs, meta2, patches2, right_dir) == 0

        if not left_ok or not right_ok:
            if not left_ok:
                os.makedirs(left_dir, exist_ok=True)
                _write_snapshot_to_dir(left_dir, meta1, patches1)
            if not right_ok:
                os.makedirs(right_dir, exist_ok=True)
                _write_snapshot_to_dir(right_dir, meta2, patches2)

        result = subprocess.run([tool, left_dir, right_dir])
        return result.returncode
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
