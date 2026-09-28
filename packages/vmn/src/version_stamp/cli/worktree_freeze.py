"""`vmn wt freeze`: pin deps to the real branches they are on, in the branch conf."""
import os

from version_stamp.cli.config_tui import (
    _get_dep_branch,
    _read_raw_conf,
    _set_dep_pin,
    _write_full_config,
)
from version_stamp.cli.worktree_git import (
    git_current_branch,
    head_contained_in_upstream,
    run_git,
)
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import (
    branch_conf_canonical_path,
    is_island_branch,
    resolve_branch_conf_path,
)


def worktree_freeze(vmn_ctx):
    vcs = vmn_ctx.vcs
    root = vcs.vmn_root_path
    branch = git_current_branch(root)
    if branch is None:
        VMN_LOGGER.error("Cannot freeze from a detached HEAD")
        return 1
    if is_island_branch(branch):
        VMN_LOGGER.error(
            f"{branch} is a private island branch. Check out the branch you will "
            "push (git checkout -b <name>) before freezing."
        )
        return 1

    conf_path = branch_conf_canonical_path(vcs.app_dir_path, branch)
    seed, _ = resolve_branch_conf_path(vcs.app_dir_path, branch)
    raw_conf = _read_raw_conf(seed)

    changed, problems = _pin_dep_branches(raw_conf, root)
    for problem in problems:
        VMN_LOGGER.error(problem)
    if problems:
        return 1
    if not changed:
        VMN_LOGGER.info("Nothing to freeze")
        return 0

    _write_full_config(conf_path, raw_conf)
    VMN_LOGGER.info(f"Wrote {conf_path}. Commit and push it with {branch}.")
    return 0


def _pin_dep_branches(raw_conf, root):
    """Pin each dep on a real branch to it. Returns (changed, problems)."""
    changed = False
    problems = []
    for rel_dir, repos in (raw_conf.get("deps") or {}).items():
        for repo_name, dep_conf in repos.items():
            if not isinstance(dep_conf, dict):
                continue
            path = os.path.join(root, rel_dir, repo_name)
            dep_branch = _get_dep_branch(path)
            if dep_branch is None:
                VMN_LOGGER.info(f"Keeping the pin of {path}: detached or missing")
            elif is_island_branch(dep_branch):
                if not head_contained_in_upstream(path):
                    problems.append(
                        f"{path} has commits only on private branch {dep_branch}. "
                        "Check out a real branch there (git checkout -b <name>) "
                        "and push it before freezing."
                    )
            elif _repin(dep_conf, dep_branch):
                changed = True
                _warn_if_unpublished(path, dep_branch)
    return changed, problems


def _repin(dep_conf, dep_branch):
    if dep_conf.get("branch") == dep_branch and not (
        dep_conf.get("hash") or dep_conf.get("tag")
    ):
        return False
    _set_dep_pin(dep_conf, "branch", dep_branch)
    return True


def _warn_if_unpublished(path, branch):
    ref = f"refs/remotes/origin/{branch}"
    result = run_git(path, ["rev-parse", "--verify", "--quiet", ref])
    if result is None or result.returncode != 0:
        VMN_LOGGER.warning(
            f"{branch} in {path} is not on origin. Push it before sharing this "
            f"conf: git push -u origin {branch}"
        )
