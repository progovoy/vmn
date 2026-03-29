#!/usr/bin/env python3
"""GitBackend — the main git-based VCS backend.

Implementation is split across mixin modules:
  - git_ops.py    — tag, push, pull, commit, clone
  - git_branch.py — branch management, checkout, state checks
  - git_tags.py   — tag/version lookup
  - git_history.py — changeset, deps, revert, log inspection
"""
import datetime
import os
import pathlib
import time

import git

from version_stamp.backends.base import VMNBackend
from version_stamp.backends.git_branch import GitBranchMixin
from version_stamp.backends.git_history import GitHistoryMixin
from version_stamp.backends.git_ops import GitOpsMixin
from version_stamp.backends.git_tags import GitTagsMixin
from version_stamp.core.constants import (
    BOLD_CHAR,
    END_CHAR,
    GIT_CACHE_TTL_MINUTES,
    VMN_BE_TYPE_GIT,
    VMN_USER_NAME,
)
from version_stamp.core.logging import VMN_LOGGER, get_call_stack, measure_runtime_decorator


# Global monkey-patch of git.cmd.Git.execute for logging and timing.
# Must be done at the class level because GitPython makes `execute` read-only
# on instances.
def _custom_git_execute(self, *args, **kwargs):
    call_stack = get_call_stack()

    if VMN_LOGGER:
        VMN_LOGGER.debug(
            f"{BOLD_CHAR}{'  ' * (len(call_stack) - 1)}{' '.join(str(v) for v in args[0])}{END_CHAR}"
        )

    original_execute = getattr(self.__class__, "_execute")
    originally_extended_output = "with_extended_output" in kwargs
    kwargs["with_extended_output"] = True

    start_time = time.perf_counter()
    ret = original_execute(self, *args, **kwargs)
    end_time = time.perf_counter()

    ret_code = 0
    sout = ""
    serr = ""
    if not originally_extended_output:
        if isinstance(ret, tuple):
            ret_code = ret[0]
            sout = ret[1]
            serr = ret[2]
            ret = sout
    elif not isinstance(ret, tuple):
        sout = ret.stdout.read()
        serr = ret.stderr.read()
        ret_code = 0
        if serr:
            ret_code = 1

    time_took = end_time - start_time

    if VMN_LOGGER:
        VMN_LOGGER.debug(
            f"{'  ' * (len(call_stack) - 1)}return code: {ret_code}, git cmd took: {time_took:.6f} seconds.\n"
            f"{'  ' * (len(call_stack) - 1)}stdout: {sout}\n"
            f"{'  ' * (len(call_stack) - 1)}stderr: {serr}"
        )

    return ret


git.cmd.Git._execute = git.cmd.Git.execute
git.cmd.Git.execute = _custom_git_execute


class GitBackend(
    GitOpsMixin,
    GitBranchMixin,
    GitTagsMixin,
    GitHistoryMixin,
    VMNBackend,
):
    @measure_runtime_decorator
    def __init__(self, repo_path, inherit_env=False):
        VMNBackend.__init__(self, VMN_BE_TYPE_GIT)

        self._be = GitBackend.initialize_git_backend(repo_path, inherit_env)

        self.add_git_user_cfg_if_missing()

        # TODO:: make selected_remote configurable.
        # Currently just selecting the first one
        self.selected_remote = self._be.remotes[0]
        self.repo_path = repo_path
        self.active_branch = self.get_active_branch()
        self.remote_active_branch = self.get_remote_tracking_branch(self.active_branch)
        self.detached_head = self.in_detached_head()

    @measure_runtime_decorator
    def perform_cached_fetch(self, force=False):
        vmn_cache_path = os.path.join(self.repo_path, ".vmn", "vmn.cache")
        if not os.path.exists(vmn_cache_path) or force:
            pathlib.Path(os.path.join(self.repo_path, ".vmn")).mkdir(
                parents=True, exist_ok=True
            )
            pathlib.Path(vmn_cache_path).touch()

            self._be.git.execute(["git", "fetch", "--tags"])
        else:
            minutes_ago = datetime.datetime.now() - datetime.timedelta(
                minutes=GIT_CACHE_TTL_MINUTES
            )
            filemtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(vmn_cache_path)
            )
            if filemtime < minutes_ago:
                pathlib.Path(vmn_cache_path).touch()
                self._be.git.execute(["git", "fetch", "--tags"])

    def __del__(self):
        self._be.close()

    @staticmethod
    @measure_runtime_decorator
    def initialize_git_backend(repo_path, inherit_env):
        be = git.Repo(repo_path, search_parent_directories=True)

        if inherit_env:
            current_git_env = {
                k: os.environ[k] for k in os.environ if k.startswith("GIT_")
            }
            current_git_env.update(
                {
                    "GIT_AUTHOR_NAME": VMN_USER_NAME,
                    "GIT_COMMITTER_NAME": VMN_USER_NAME,
                    "GIT_AUTHOR_EMAIL": VMN_USER_NAME,
                    "GIT_COMMITTER_EMAIL": VMN_USER_NAME,
                }
            )
            be.git.update_environment(**current_git_env)

        return be

    @staticmethod
    @measure_runtime_decorator
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        except Exception:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remotes[0].urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        finally:
            client.close()

        return hash, remote, "git"
