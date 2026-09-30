"""Git operations used by worktree-island lifecycle management."""
import os
import shutil

from version_stamp.core import git_cmd
from version_stamp.core.constants import ISLAND_BRANCH_PREFIX, VMN_READONLY_REMOTE
from version_stamp.core.git_cmd import git_stdout as _git_stdout
from version_stamp.core.logging import VMN_LOGGER

# A plain path, not "host:path": a colon makes git try ssh and print a
# confusing "Could not resolve hostname" error.
READONLY_PUSH_URL = "/vmn-readonly/island-branches-are-not-pushable"


def run_git(repo_path, args, stdin=None, text=True):
    """git in *repo_path*; text output unless *text* is False (patches)."""
    return git_cmd.run_git(repo_path, args, stdin=stdin, text=text)


def git_current_branch(repo_path):
    result = run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    if result and result.returncode == 0 and result.stdout.strip() != "HEAD":
        return result.stdout.strip()
    return None


def git_remote_url(repo_path, remote=None):
    """The URL of *remote*, by default the repo's primary (non-mirror) one."""
    return git_cmd.remote_url(repo_path, remote)


def branch_upstream(repo_path, branch):
    """The upstream of *branch* (e.g. 'origin/main'), or None."""
    return _git_stdout(
        repo_path,
        [
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        ],
    )


def head_contained_in_upstream(repo_path):
    """True when HEAD has no commits beyond its branch's upstream."""
    result = run_git(repo_path, ["merge-base", "--is-ancestor", "HEAD", "@{upstream}"])
    return bool(result and result.returncode == 0)


def git_head(repo_path):
    return _git_stdout(repo_path, ["rev-parse", "HEAD"])


def is_dirty(repo_path):
    """Tracked edits or untracked files (GitBackend's pending check ignores
    untracked ones)."""
    return bool(_git_stdout(repo_path, ["status", "--porcelain"]))


def ensure_readonly_remote(repo_path, source_remote=None):
    """Create or refresh the read-only mirror of *source_remote* (default: the
    primary remote).

    It fetches from the same URL but its push URL cannot work, and it has no
    fetch refspecs until fetch_readonly_branch adds them. False when the repo
    has no *source_remote*.
    """
    url = git_remote_url(repo_path, source_remote)
    if not url:
        return False
    if git_remote_url(repo_path, VMN_READONLY_REMOTE) is None:
        run_git(repo_path, ["remote", "add", VMN_READONLY_REMOTE, url])
        run_git(
            repo_path, ["config", "--unset-all", f"remote.{VMN_READONLY_REMOTE}.fetch"]
        )
    else:
        run_git(repo_path, ["remote", "set-url", VMN_READONLY_REMOTE, url])
    run_git(
        repo_path,
        ["remote", "set-url", "--push", VMN_READONLY_REMOTE, READONLY_PUSH_URL],
    )
    return True


def fetch_readonly_branch(repo_path, branch):
    """Fetch *branch* through the read-only remote and keep tracking it."""
    refspec = f"+refs/heads/{branch}:refs/remotes/{VMN_READONLY_REMOTE}/{branch}"
    result = run_git(repo_path, ["fetch", VMN_READONLY_REMOTE, refspec])
    if result is None or result.returncode != 0:
        return False
    key = f"remote.{VMN_READONLY_REMOTE}.fetch"
    if refspec not in (_git_stdout(repo_path, ["config", "--get-all", key]) or ""):
        run_git(repo_path, ["config", "--add", key, refspec])
    return True


def track_privately(repo_path, private_branch, upstream):
    """Track *upstream* and send any bare push of *private_branch* nowhere."""
    result = run_git(
        repo_path, ["branch", f"--set-upstream-to={upstream}", private_branch]
    )
    if result is None or result.returncode != 0:
        VMN_LOGGER.error(f"Failed to set upstream {upstream} for {private_branch}")
        return False
    run_git(
        repo_path,
        ["config", f"branch.{private_branch}.pushRemote", VMN_READONLY_REMOTE],
    )
    return True


def remove_readonly_remote_if_unused(repo_path):
    """Drop the read-only remote once no island branch is left in the repo."""
    island_refs = f"refs/heads/{ISLAND_BRANCH_PREFIX}"
    if _git_stdout(repo_path, ["for-each-ref", "--count=1", island_refs]):
        return
    if git_remote_url(repo_path, VMN_READONLY_REMOTE) is not None:
        run_git(repo_path, ["remote", "remove", VMN_READONLY_REMOTE])


def create_main_worktree(repo_path, dest_path, branch_name, source):
    start_point = source.get("commit")
    if source["type"] == "branch":
        start_point = source["ref"]

    cmd = ["worktree", "add", "-b", branch_name, str(dest_path)]
    if start_point:
        cmd.append(start_point)

    result = run_git(repo_path, cmd)
    if result is None or result.returncode != 0:
        message = result.stderr.strip() if result else "unknown error"
        VMN_LOGGER.error(f"Failed to create main worktree: {message}")
        return 1
    return 0


def create_dep_worktree(repo_path, dest_path, dep_info, branch_name):
    start_point = dep_info["start_point"]
    if branch_name:
        cmd = ["worktree", "add", "-b", branch_name, str(dest_path)]
    else:
        cmd = ["worktree", "add", "--detach", str(dest_path)]
    if start_point:
        cmd.append(start_point)

    result = run_git(repo_path, cmd)
    if result is None or result.returncode != 0:
        message = result.stderr.strip() if result else "unknown error"
        VMN_LOGGER.error(f"Failed to create dep worktree at {dest_path}: {message}")
        return 1
    return 0


def shallow_clone_dep(dep_info, dest_path, branch_name=None):
    remote = dep_info.get("remote")
    if not remote:
        VMN_LOGGER.error("No remote URL for shallow clone")
        return 1
    return git_cmd.clone_at_commit(
        dest_path,
        remote,
        dep_info.get("hash"),
        branch=dep_info.get("branch"),
        new_branch=branch_name,
    )


def cleanup_island(
    main_repo_path,
    main_dest,
    island_branch,
    dep_manifests,
    run_git=run_git,
    island_path=None,
):
    success = True
    for dep_info in dep_manifests.values():
        source_path = dep_info.get("source_path")
        if source_path and not remove_registered_worktree(
            source_path,
            dep_info["path"],
            dep_info.get("branch"),
            run_git,
        ):
            success = False

    if not remove_registered_worktree(
        main_repo_path, main_dest, island_branch, run_git
    ):
        success = False

    if success:
        shutil.rmtree(island_path or os.path.dirname(str(main_dest)), ignore_errors=True)
    return success


def remove_registered_worktree(repo_path, worktree_path, branch=None, run_git=run_git):
    if worktree_registered(repo_path, worktree_path, run_git):
        result = run_git(
            repo_path, ["worktree", "remove", "--force", str(worktree_path)]
        )
        if result is None or result.returncode != 0:
            message = result.stderr.strip() if result else "unknown error"
            VMN_LOGGER.error(f"Failed to remove worktree {worktree_path}: {message}")
            return False

    if branch and branch_exists(repo_path, branch, run_git):
        result = run_git(repo_path, ["branch", "-D", branch])
        if result is None or result.returncode != 0:
            message = result.stderr.strip() if result else "unknown error"
            VMN_LOGGER.error(f"Failed to delete worktree branch {branch}: {message}")
            return False
    return True


def worktree_registered(repo_path, worktree_path, run_git=run_git):
    result = run_git(repo_path, ["worktree", "list", "--porcelain"])
    if result is None or result.returncode != 0:
        return True
    expected = os.path.realpath(str(worktree_path))
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            registered = os.path.realpath(line[len("worktree ") :])
            if registered == expected:
                return True
    return False


def branch_exists(repo_path, branch, run_git=run_git):
    result = run_git(repo_path, ["show-ref", "--verify", f"refs/heads/{branch}"])
    return bool(result and result.returncode == 0)


def source_repo_from_worktree(worktree_path, run_git=run_git):
    result = run_git(worktree_path, ["rev-parse", "--git-common-dir"])
    if result is None or result.returncode != 0:
        return None
    common_dir = result.stdout.strip()
    if not os.path.isabs(common_dir):
        common_dir = os.path.join(str(worktree_path), common_dir)
    common_dir = os.path.realpath(common_dir)
    source_path = os.path.dirname(common_dir)
    if source_path == os.path.realpath(str(worktree_path)):
        return None
    return source_path
