#!/usr/bin/env python3
"""A git workspace's branch, HEAD and dirty flag for the shell's context root.

One ``git status`` process, run with ``--no-optional-locks`` so it never takes
``index.lock`` and races a concurrent ``vmn stamp`` or Actions job. Untracked
files do not count as dirty. A failure still answers, with an ``error``.
"""
import os
import subprocess

from vmn_exp.storage.areas import local_store_root

GIT_STATUS = [
    "git", "--no-optional-locks", "status",
    "--porcelain=v2", "--branch", "--untracked-files=no",
]
TIMEOUT_SEC = 2


def parse_status(text):
    """``{branch, detached, head, head_short, dirty}`` of porcelain v2 output."""
    branch, head, dirty = None, None, False
    for line in text.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.split(" ", 2)[2]
            head = None if oid == "(initial)" else oid
        elif line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line and not line.startswith("#"):
            dirty = True
    detached = branch == "(detached)"
    return {
        "branch": None if detached else branch,
        "detached": detached,
        "head": head,
        "head_short": head and head[:7],
        "dirty": dirty,
    }


def _failure(error):
    return {"branch": None, "detached": False, "head": None, "head_short": None,
            "dirty": None, "error": error}


def _status(path):
    try:
        result = subprocess.run(
            GIT_STATUS, cwd=path, capture_output=True, text=True, timeout=TIMEOUT_SEC
        )
    except subprocess.TimeoutExpired:
        return _failure("timeout")
    except OSError as exc:  # no git binary
        return _failure(str(exc))
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        return _failure(lines[0] if lines else f"git exited {result.returncode}")
    return parse_status(result.stdout)


def git_context(path):
    """The checkout at *path*'s git context, with where the ui reads its runs."""
    return dict(_status(path), store=os.path.relpath(local_store_root(path), path))
