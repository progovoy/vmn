"""Per-repo vmn lock that serializes mutations of a checkout.

Factored out of ``core.experiment_writer`` so stamping entry points can import
it without pulling in any experiment-tracking modules.
"""
import os

from filelock import FileLock

from version_stamp.core.constants import LOCK_FILE_ENV, LOCK_FILENAME


def get_repo_lock(vmn_root_path):
    """Return a FileLock for the given repo root.

    One definition for every entry point: the CLI holds it around a command,
    and ``version_stamp.exp.start_run`` holds it around the mutating create
    phase.  ``$VMN_LOCK_FILE_PATH`` overrides the path for the whole process,
    which is what a user pointing vmn at a shared lock expects.
    """
    return FileLock(
        os.environ.get(LOCK_FILE_ENV)
        or os.path.join(vmn_root_path, ".vmn", LOCK_FILENAME)
    )
