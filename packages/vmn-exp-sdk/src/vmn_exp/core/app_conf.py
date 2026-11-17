"""The ``experiment:`` section of an app's conf: off the vcs that loaded it
(:func:`experiment_conf`), or read straight from the checkout by callers that
hold no vcs (:func:`read_experiment_conf` — the reader API, alerts when no conf
was handed over; :func:`read_app_conf` — the store a reader resolves). They
read the conf file vmn's writer loads: the current branch's conf when one
exists, else ``.vmn/<app>/conf.yml``."""
import logging
import os

from version_stamp.store.conf_paths import branch_conf_candidates
from vmn_exp import _base

_LOGGER = logging.getLogger(__name__)
_HEAD_REF = "ref: refs/heads/"
_GITDIR = "gitdir:"


def experiment_conf(vcs):
    """The ``experiment:`` section of *vcs*'s conf.yml, ``{}`` without one."""
    return getattr(vcs, "experiment", None) or {}


def read_experiment_conf(app_name, root=None):
    """``conf.experiment`` of the app's conf under *root* (default: the
    current checkout), or {}. Never raises."""
    return read_app_conf(app_name, root).get("experiment") or {}


def read_app_conf(app_name, root=None):
    """The ``conf:`` mapping of the app's conf under *root* (default: the
    current checkout), or {}: what a reader resolves the store from
    (``store``, legacy ``experiment.storage``). Never raises."""
    if not app_name:
        return {}
    try:
        return app_conf_from(root or _base.resolve_root_path(), app_name, _read_text)
    except Exception:
        _LOGGER.debug(f"No conf for {app_name}", exc_info=True)
        return {}


def _read_text(path):
    with open(path) as f:
        return f.read()


def app_conf_from(root, app_name, read_text):
    """The ``conf:`` mapping of the first conf file vmn loads for *app_name*
    on the branch checked out at *root* (``{}`` without one), every file read
    through *read_text*."""
    app_dir = os.path.join(root, ".vmn", *app_name.split("/"))
    for path in branch_conf_candidates(app_dir, current_branch(root, read_text)):
        try:
            text = read_text(path)
        except OSError:
            continue
        return (_base.yaml_safe_load(text) or {}).get("conf") or {}
    return {}


def current_branch(root, read_text):
    """The branch checked out at *root* off its ``HEAD`` (a worktree's
    ``.git`` file points at its git dir), or None when detached or no repo."""
    git_dir = os.path.join(root, ".git")
    try:
        pointer = read_text(git_dir).strip()
    except OSError:  # a directory, or none
        pointer = ""
    if pointer.startswith(_GITDIR):
        git_dir = os.path.normpath(os.path.join(root, pointer[len(_GITDIR):].strip()))
    try:
        head = read_text(os.path.join(git_dir, "HEAD")).strip()
    except OSError:
        return None
    return head[len(_HEAD_REF):] if head.startswith(_HEAD_REF) else None
