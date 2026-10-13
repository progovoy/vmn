#!/usr/bin/env python3
import git

from version_stamp.backends.git import GitBackend
from version_stamp.backends.local_file import LocalFileBackend
from version_stamp.core.constants import VMN_BE_TYPE_GIT, VMN_BE_TYPE_LOCAL_FILE
from version_stamp.core.logging import measure_runtime_decorator


@measure_runtime_decorator
def get_client(root_path, be_type, inherit_env=False, use_ci_hint=False):
    if be_type == VMN_BE_TYPE_LOCAL_FILE:
        be = LocalFileBackend(root_path)
        return be, None

    try:
        be = GitBackend(root_path, inherit_env, use_ci_hint=use_ci_hint)
        return be, None
    except git.exc.InvalidGitRepositoryError:
        err = f"repository path: {root_path} is not a functional git or repository.\n"
        return None, err


def checkout_branch_of(root_path):
    """The branch vmn reads branch confs for at *root_path*: the checked-out
    branch, or the one a detached HEAD resolves to as the main repo's does
    (CI env hint > branch last checked out > unique tip > unique container >
    alphabetical; plan 17). None when no branch qualifies or *root_path* is
    no git repo. Runs git for a detached HEAD."""
    be, _ = get_client(root_path, VMN_BE_TYPE_GIT, use_ci_hint=True)
    return be.active_branch if be is not None else None
