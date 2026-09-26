"""`vmn wt pull`: rebase each private island branch onto its source branch."""
import json
import os

from version_stamp.cli.worktree_git import git_current_branch, is_dirty, run_git
from version_stamp.cli.worktree_state import ISLAND_MANIFEST_FILENAME
from version_stamp.core.logging import VMN_LOGGER


def worktree_pull(vmn_ctx):
    manifest_path = _find_manifest(vmn_ctx)
    if manifest_path is None:
        return 1
    with open(manifest_path) as stream:
        manifest = json.load(stream)

    repos = [manifest["main_repo"], *manifest.get("deps", {}).values()]
    failed = [repo["path"] for repo in repos if not _pull_repo(repo)]
    return 1 if failed else 0


def _find_manifest(vmn_ctx):
    """The island manifest named on the command line, or the one around cwd."""
    name = vmn_ctx.args.name
    if name:
        base = os.path.join(vmn_ctx.vcs.vmn_root_path, vmn_ctx.args.base_path)
        path = os.path.join(os.path.abspath(base), name, ISLAND_MANIFEST_FILENAME)
        if os.path.isfile(path):
            return path
        VMN_LOGGER.error(f"Island not found: {name}")
        return None

    directory = os.path.realpath(vmn_ctx.vcs.vmn_root_path)
    while True:
        path = os.path.join(directory, ISLAND_MANIFEST_FILENAME)
        if os.path.isfile(path):
            return path
        parent = os.path.dirname(directory)
        if parent == directory:
            VMN_LOGGER.error("Not inside an island; pass the island name")
            return None
        directory = parent


def _pull_repo(repo):
    """Rebase one checkout if it is still on its private branch. False on error."""
    path, private = repo["path"], repo.get("branch")
    if not private or not repo.get("source_branch"):
        return True
    current = git_current_branch(path)
    if current != private:
        VMN_LOGGER.info(f"Skipping {path}: on {current}, not {private}")
        return True
    if is_dirty(path):
        VMN_LOGGER.error(f"Skipping {path}: uncommitted changes")
        return False

    result = run_git(path, ["pull", "--rebase"])
    if result is None or result.returncode != 0:
        message = result.stderr.strip() if result else "unknown error"
        VMN_LOGGER.error(
            f"Rebase failed in {path}: {message}\n"
            f"Resolve, then run git rebase --continue (or git rebase --abort) in {path}"
        )
        return False
    VMN_LOGGER.info(f"{path}: rebased onto {repo.get('upstream')}")
    return True
