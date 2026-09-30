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
import re
import time

import git

from version_stamp.backends.base import VMNBackend
from version_stamp.backends.git_branch import GitBranchMixin
from version_stamp.backends.git_history import (
    GitHistoryMixin,
    remote_location,
    select_remote,
)
from version_stamp.backends.git_ops import GitOpsMixin
from version_stamp.backends.git_tag_parse import GitTagParseMixin
from version_stamp.backends.git_tags import GitTagsMixin
from version_stamp.core.constants import (
    BOLD_CHAR,
    END_CHAR,
    GIT_CACHE_TTL_MINUTES,
    VMN_BE_TYPE_GIT,
    VMN_USER_NAME,
)
from version_stamp.core.logging import (
    VMN_LOGGER,
    debug_enabled,
    get_call_stack,
    measure_runtime_decorator,
)

_CREDENTIALS_RE = re.compile(r"(https?://)([^@]+)@")


def _sanitize_log_str(s):
    """Mask credentials in URLs (e.g. https://user:token@host → https://***@host)."""
    return _CREDENTIALS_RE.sub(r"\1***@", s)


_GIT_OUTPUT_LOG_LIMIT = 2048


def _loggable_output(output):
    """*output* for the log: head only (unless --debug), credentials masked."""
    s = str(output)
    if not debug_enabled() and len(s) > _GIT_OUTPUT_LOG_LIMIT:
        dropped = len(s) - _GIT_OUTPUT_LOG_LIMIT
        s = f"{s[:_GIT_OUTPUT_LOG_LIMIT]}... {dropped} bytes truncated"
    return _sanitize_log_str(s)


# Global monkey-patch of git.cmd.Git.execute for logging and timing.
# Must be done at the class level because GitPython makes `execute` read-only
# on instances.
def _custom_git_execute(self, *args, **kwargs):
    call_stack = get_call_stack()

    if VMN_LOGGER:
        raw_cmd = " ".join(str(v) for v in args[0])
        VMN_LOGGER.debug(
            f"{BOLD_CHAR}{'  ' * (len(call_stack) - 1)}{_sanitize_log_str(raw_cmd)}{END_CHAR}"
        )

    original_execute = self.__class__._execute
    # A process handle's streams belong to the caller (e.g. Repo.clone_from
    # reads stderr for its error message), so they are never read here.
    as_process = kwargs.get("as_process", False)
    originally_extended_output = kwargs.get("with_extended_output", False)
    if not as_process:
        kwargs["with_extended_output"] = True

    start_time = time.perf_counter()
    ret = original_execute(self, *args, **kwargs)
    end_time = time.perf_counter()

    ret_code = 0
    sout = ""
    serr = ""
    if not as_process and isinstance(ret, tuple):
        ret_code, sout, serr = ret
        if not originally_extended_output:
            ret = sout

    time_took = end_time - start_time

    if VMN_LOGGER:
        VMN_LOGGER.debug(
            f"{'  ' * (len(call_stack) - 1)}return code: {ret_code}, git cmd took: {time_took:.6f} seconds.\n"
            f"{'  ' * (len(call_stack) - 1)}stdout: {_loggable_output(sout)}\n"
            f"{'  ' * (len(call_stack) - 1)}stderr: {_loggable_output(serr)}"
        )

    return ret


def _cache_expired(vmn_cache_path):
    if not os.path.exists(vmn_cache_path):
        return True
    ttl_start = datetime.datetime.now() - datetime.timedelta(
        minutes=GIT_CACHE_TTL_MINUTES
    )
    return datetime.datetime.fromtimestamp(os.path.getmtime(vmn_cache_path)) < ttl_start


git.cmd.Git._execute = git.cmd.Git.execute
git.cmd.Git.execute = _custom_git_execute


class GitBackend(
    GitOpsMixin,
    GitBranchMixin,
    GitTagsMixin,
    GitTagParseMixin,
    GitHistoryMixin,
    VMNBackend,
):
    @measure_runtime_decorator
    def __init__(self, repo_path, inherit_env=False, read_only=False):
        VMNBackend.__init__(self, VMN_BE_TYPE_GIT)
        self.read_only = read_only

        self._be = GitBackend.initialize_git_backend(repo_path, inherit_env)

        self.add_git_user_cfg_if_missing()

        # TODO:: make selected_remote configurable.
        # Currently just selecting the first one. None when no remote is
        # configured — local read commands still work; remote-requiring
        # commands fail fast (see cli/entry.py).
        self.selected_remote = select_remote(self._be)
        self.repo_path = repo_path
        self.remote_active_branch = None
        self.active_branch = self.get_active_branch()
        if self.remote_active_branch is None:
            self.remote_active_branch = self.get_remote_tracking_branch(
                self.active_branch
            )
        self.detached_head = self.in_detached_head()

    @measure_runtime_decorator
    def perform_cached_fetch(self, force=False):
        vmn_cache_path = os.path.join(self.repo_path, ".vmn", "vmn.cache")
        if not force and not _cache_expired(vmn_cache_path):
            return

        pathlib.Path(os.path.join(self.repo_path, ".vmn")).mkdir(
            parents=True, exist_ok=True
        )
        pathlib.Path(vmn_cache_path).touch()
        self._fetch("--tags")

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
            # None when no remote is configured — the repo entry is kept.
            remote = remote_location(select_remote(client), client.working_dir)
        except Exception:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        finally:
            client.close()

        return hash, remote, "git"
