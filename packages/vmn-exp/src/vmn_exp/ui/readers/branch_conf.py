#!/usr/bin/env python3
"""The conf.yml an app of a checkout reads on the checkout's branch: the
branch conf when there is one (resolved as ``vmn`` resolves it: canonical
``branch_conf/<branch>/conf.yml`` > flat > legacy), else ``.vmn/<app>/conf.yml``.

The branch comes from ``HEAD`` read as a file (a worktree's ``.git`` file
points at its gitdir), so a list poll costs a few small reads, no git
process; a detached or unreadable ``HEAD`` reads the app conf.
"""
import os

from version_stamp.api import resolve_branch_conf_path

_HEADS = "ref: refs/heads/"
_GITDIR = "gitdir:"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def checkout_branch(root_path):
    """The branch checked out at *root_path*, None when detached or unknown."""
    git_dir = os.path.join(root_path, ".git")
    if os.path.isfile(git_dir):
        pointer = _read(git_dir) or ""
        if not pointer.startswith(_GITDIR):
            return None
        git_dir = os.path.join(root_path, pointer[len(_GITDIR):].strip())
    head = _read(os.path.join(git_dir, "HEAD")) or ""
    return head[len(_HEADS):] if head.startswith(_HEADS) else None


def app_conf_path(root_path, app_name):
    """The conf.yml *app_name* reads on the checkout's branch."""
    app_dir = os.path.join(root_path, ".vmn", *app_name.split("/"))
    return resolve_branch_conf_path(app_dir, checkout_branch(root_path))[0]
