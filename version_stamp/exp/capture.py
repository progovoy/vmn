#!/usr/bin/env python3
"""Snapshot capture for ``start_run``: outside the repo lock, once per tree state.

Capturing is the expensive part of creating a run — ``git diff``, format-patch,
hashing untracked files and tar+gzipping them (up to the snapshot caps). None of
it mutates the repository, so it runs *before* the repo lock is taken; only the
verstr claim needs the lock. A sweep's trials therefore capture in parallel.

Within one process the untracked tarball — the only costly piece that is not
already cached on disk — is memoized by the tree's identity: ``(repo, HEAD,
diff hash)``. The diff hash already covers the tracked diff, unpushed commits and
the untracked files' *contents* (hashed through the ``(size, mtime)`` cache in
``.vmn/untracked_hash.cache``), so trials 2..N of an unchanged tree reuse trial
1's tarball instead of rebuilding it. One entry is kept: a sweep runs one tree.
"""
import os
import threading
from dataclasses import dataclass

from version_stamp.cli.snapshot import (
    _compute_diff_hash,
    _untracked_caps,
    gather_create_data,
    untracked_payload,
)
from version_stamp.core.logging import VMN_LOGGER

_MEMO = {"key": None, "payloads": None}
_MEMO_LOCK = threading.Lock()


@dataclass
class Capture:
    """What a new run records about the code it runs.

    *identity* is what the diff hash and code verstr are computed from;
    *payload* is what is stored — the same patches plus the untracked tarball,
    or nothing at all for ``snapshot=False``.
    """

    base_version: str
    commit_hash: str
    identity: dict
    payload: dict
    dirty_states: list
    ver_info: dict
    snapshot: bool
    diff_hash: str


def capture_snapshot(vcs, snapshot=True, status=None):
    """``(Capture, None)``, or ``(None, error_code)`` when the app is not stamped.

    *status* is a repo status the caller already has (see ``gather_create_data``).
    """
    base_version, commit_hash, identity, dirty_states, ver_info, err = (
        gather_create_data(vcs, allow_clean=True, lightweight=True, status=status)
    )
    if err is not None:
        return None, err
    diff_hash = _compute_diff_hash(identity)
    payload = (
        _with_untracked_payloads(vcs, commit_hash, diff_hash, identity)
        if snapshot
        else {}
    )
    capture = Capture(
        base_version,
        commit_hash,
        identity,
        payload,
        dirty_states,
        ver_info,
        snapshot,
        diff_hash,
    )
    return capture, None


def _with_untracked_payloads(vcs, commit_hash, diff_hash, identity):
    """*identity* plus the untracked tarballs of the repo and its deps."""
    key = (vcs.vmn_root_path, commit_hash, diff_hash, _untracked_caps())
    with _MEMO_LOCK:
        payloads = _MEMO["payloads"] if _MEMO["key"] == key else None
    if payloads is None:
        payloads = _collect_payloads(vcs, identity)
        with _MEMO_LOCK:
            _MEMO["key"], _MEMO["payloads"] = key, payloads
    return _merge(identity, payloads)


def _repos_with_untracked(vcs, identity):
    """``{dep_path or None: repo_path}`` of the repos that have untracked files."""
    repos = {}
    if identity.get("untracked_hash"):
        repos[None] = vcs.backend.repo_path
    for dep_path, dep in identity.get("deps", {}).items():
        if dep.get("untracked_hash"):
            repos[dep_path] = os.path.join(vcs.vmn_root_path, dep_path)
    return repos


def _collect_payloads(vcs, identity):
    payloads = {}
    for dep_path, repo_path in _repos_with_untracked(vcs, identity).items():
        try:
            payloads[dep_path] = untracked_payload(repo_path)
        except Exception:
            VMN_LOGGER.debug("Failed to collect untracked files", exc_info=True)
    return payloads


def _merge(identity, payloads):
    """A copy of *identity* with the payloads added — the memo is never mutated."""
    merged = dict(identity)
    if identity.get("deps"):
        merged["deps"] = {path: dict(dep) for path, dep in identity["deps"].items()}
    for dep_path, payload in payloads.items():
        target = merged if dep_path is None else merged["deps"][dep_path]
        target.update(payload)
    return merged
