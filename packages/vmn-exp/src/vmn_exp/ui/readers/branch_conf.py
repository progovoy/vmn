#!/usr/bin/env python3
"""The conf.yml an app of a checkout reads on the checkout's branch: the
branch conf when there is one (resolved as ``vmn`` resolves it: canonical
``branch_conf/<branch>/conf.yml`` > flat > legacy), else ``.vmn/<app>/conf.yml``.

The branch comes from ``HEAD`` read as a file (a worktree's ``.git`` file
points at its gitdir), so a list poll on a branch costs a few small reads,
no git process. A detached ``HEAD`` takes the branch ``vmn`` resolves it to
(CI env hint > branch last checked out > unique tip > ..., plan 17), which
runs git once per (checkout, HEAD commit); no branch, or an unreadable
``HEAD``, reads the app conf.
"""
import functools
import os

import version_stamp.api as vmn_api

_HEADS = "ref: refs/heads/"
_GITDIR = "gitdir:"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _head(root_path):
    """The checkout's ``HEAD`` file content, or None when unreadable."""
    git_dir = os.path.join(root_path, ".git")
    if os.path.isfile(git_dir):
        pointer = _read(git_dir) or ""
        if not pointer.startswith(_GITDIR):
            return None
        git_dir = os.path.join(root_path, pointer[len(_GITDIR):].strip())
    return _read(os.path.join(git_dir, "HEAD"))


@functools.lru_cache(maxsize=64)
def detached_branch(root_path, head_sha):
    """The branch vmn resolves *root_path*'s detached HEAD (at *head_sha*,
    the cache key) to; None when none qualifies or git fails."""
    try:
        return vmn_api.checkout_branch_of(root_path)
    except Exception:  # a broken checkout reads the app conf, never a 500
        return None


def checkout_branch(root_path):
    """The branch checked out at *root_path* (a detached HEAD's as vmn
    resolves it), None when there is none or ``HEAD`` is unreadable."""
    head = _head(root_path)
    if not head:
        return None
    if head.startswith(_HEADS):
        return head[len(_HEADS):]
    return detached_branch(root_path, head)


def app_conf_path(root_path, app_name):
    """The conf.yml *app_name* reads on the checkout's branch."""
    app_dir = os.path.join(root_path, ".vmn", *app_name.split("/"))
    return vmn_api.resolve_branch_conf_path(app_dir, checkout_branch(root_path))[0]
