"""Check a commit out into a fresh directory: from a local repository when it
has the commit, else from a remote (shallow first). Every git call is bounded
by a timeout."""
import os

from version_stamp.core import git_cmd

# Seconds a git subprocess may take while materializing a snapshot: local
# operations are quick, network ones must not hang an export or a ui diff.
_LOCAL_GIT_TIMEOUT_SEC = 120


def _git_ok(args, cwd=None, timeout=_LOCAL_GIT_TIMEOUT_SEC, what=None):
    return git_cmd.git_ok(cwd, args, timeout=timeout, what=what)


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


def _clone_at(dest, local_repo, remote, commit_hash):
    """Materialize *commit_hash* from the local repo when it has it, else remote."""
    if _commit_exists(local_repo, commit_hash):
        return _clone_local_at(dest, local_repo, commit_hash)
    return git_cmd.clone_at_commit(dest, remote, commit_hash)
