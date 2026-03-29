#!/usr/bin/env python3
import git

from version_stamp.backends.git import GitBackend
from version_stamp.backends.local_file import LocalFileBackend
from version_stamp.core.logging import measure_runtime_decorator


@measure_runtime_decorator
def get_client(root_path, be_type, inherit_env=False):
    if be_type == "local_file":
        be = LocalFileBackend(root_path)
        return be, None

    try:
        client = git.Repo(root_path, search_parent_directories=True)
        client.close()

        be = GitBackend(root_path, inherit_env)
        return be, None
    except git.exc.InvalidGitRepositoryError:
        err = f"repository path: {root_path} is not a functional git or repository.\n"
        return None, err
