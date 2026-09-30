"""Plain git subprocess plumbing shared by islands, dev versions and backends.

Output is bytes unless ``text=True``, so non-UTF-8 diffs pass through intact.
A git that cannot be run or times out gives None instead of raising.
"""
import os
import shutil
import subprocess

from version_stamp.core.constants import VMN_READONLY_REMOTE
from version_stamp.core.logging import VMN_LOGGER

# Seconds a clone/fetch from a remote may take before it is abandoned.
NETWORK_GIT_TIMEOUT_SEC = 300


def run_git(repo, args, stdin=None, timeout=None, text=False):
    """Run ``git [-C repo] args``; a CompletedProcess, or None when git could
    not be run or timed out."""
    cmd = ["git", *(["-C", str(repo)] if repo is not None else []), *args]
    try:
        return subprocess.run(
            cmd, input=stdin, capture_output=True, text=text, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        VMN_LOGGER.error(f"git {' '.join(args[:2])} timed out after {timeout}s")
    except Exception as exc:
        VMN_LOGGER.debug(f"git command failed: {cmd} - {exc}")
    return None


def git_ok(repo, args, timeout=None, what=None):
    """Whether git succeeded; logs *what* failed (with git's stderr) if given."""
    result = run_git(repo, args, timeout=timeout, text=True)
    if result is not None and result.returncode == 0:
        return True
    if what and result is not None:
        VMN_LOGGER.error(f"{what} failed: {result.stderr}")
    return False


def git_stdout(repo, args, timeout=None):
    """git's stripped text output, or None when it failed."""
    result = run_git(repo, args, timeout=timeout, text=True)
    if result is not None and result.returncode == 0:
        return result.stdout.strip()
    return None


def primary_remote(repo):
    """The first configured remote that is not the island read-only mirror."""
    urls = git_stdout(repo, ["config", "--get-regexp", r"^remote\..*\.url$"]) or ""
    for line in urls.splitlines():
        name = line.split(" ", 1)[0][len("remote.") : -len(".url")]
        if name != VMN_READONLY_REMOTE:
            return name
    return None


def remote_url(repo, remote=None):
    """The fetch URL of *remote* (default: the primary remote), or None."""
    remote = remote or primary_remote(repo)
    if remote is None:
        return None
    return git_stdout(repo, ["remote", "get-url", remote])


def clone_at_commit(dest, remote, commit, branch=None, new_branch=None):
    """Clone *remote* into *dest* at *commit* (else *branch*'s tip), checked out
    on *new_branch* or detached, with *remote* as ``origin``. 0 or 1.

    A shallow fetch is tried first; a full clone is the fallback."""
    if os.path.exists(remote):
        remote = os.path.abspath(remote)
    if _shallow_fetch_checkout(dest, remote, commit or branch or "HEAD", new_branch):
        return _verify_head(dest, commit)
    if not commit:
        return 1
    VMN_LOGGER.warning(
        f"Shallow fetch failed for {commit[:7]}, falling back to full clone"
    )
    shutil.rmtree(dest, ignore_errors=True)
    if not git_ok(
        None,
        ["clone", "--no-checkout", remote, str(dest)],
        timeout=NETWORK_GIT_TIMEOUT_SEC,
        what="git clone",
    ):
        return 1
    if not git_ok(
        dest,
        ["checkout", *_checkout_mode(new_branch), commit],
        timeout=NETWORK_GIT_TIMEOUT_SEC,
        what=f"git checkout {commit[:7]}",
    ):
        return 1
    return _verify_head(dest, commit)


def _shallow_fetch_checkout(dest, remote, ref, new_branch):
    os.makedirs(dest, exist_ok=True)
    timeout = NETWORK_GIT_TIMEOUT_SEC
    return (
        git_ok(dest, ["init", "--quiet"], timeout=timeout, what=f"git init in {dest}")
        and git_ok(dest, ["remote", "add", "origin", remote], timeout=timeout)
        and git_ok(dest, ["fetch", "--depth", "1", "origin", ref], timeout=timeout)
        and git_ok(
            dest,
            ["checkout", "--quiet", *_checkout_mode(new_branch), "FETCH_HEAD"],
            timeout=timeout,
        )
    )


def _checkout_mode(new_branch):
    return ["-b", new_branch] if new_branch else ["--detach"]


def _verify_head(dest, commit):
    head = git_stdout(dest, ["rev-parse", "HEAD"]) or ""
    if commit and not head.startswith(commit):
        VMN_LOGGER.error(f"Clone at {dest} did not reach {commit}")
        return 1
    return 0
