"""Snapshot capture: a tree's identity cheaply, its code object only once.

Capturing is the expensive part of a snapshot or a run — ``git diff``,
format-patch, hashing untracked files and tar+gzipping them (up to the
snapshot caps). None of it mutates the repository, so callers run it *before*
taking the repo lock.

The identity — base version, commit and diff hash — is always computed; it is
cheap, since the diff hash covers the untracked files' *contents* through the
``(size, mtime)`` cache in ``.vmn/untracked_hash.cache``. The payload (the
untracked tarball above all) is built only when the code store has no complete
object for that identity yet (:mod:`.code_store`), so an unchanged tree builds
and uploads nothing but its own records.

Public:
  - ``SnapshotCapture`` — ``base_version``, ``commit_hash``, ``identity``
    (patches minus the untracked tarball), ``dirty_states``, ``ver_info``,
    ``diff_hash``; ``code_verstr`` property.
  - ``capture_identity(vcs, status=None) -> (SnapshotCapture, None) |
    (None, error_code)``.
  - ``ensure_code(code_store, vcs, captured) -> (key | None, summary)``.
"""
import os
from dataclasses import dataclass

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion import untracked
from version_stamp.devversion.capture import (
    _compute_diff_hash,
    _format_dev_verstr,
    gather_create_data,
)
from version_stamp.snapshot.code_store import code_key, publish_code, store_code, stored_code
from version_stamp.snapshot.record import patch_summary


@dataclass
class SnapshotCapture:
    """What a snapshot or run records about the code in the tree.

    *identity* is what the diff hash and code verstr are computed from: the
    patches minus the untracked tarball.
    """

    base_version: str
    commit_hash: str
    identity: dict
    dirty_states: list
    ver_info: dict
    diff_hash: str

    @property
    def code_verstr(self):
        return _format_dev_verstr(self.base_version, self.commit_hash, self.diff_hash)


def capture_identity(vcs, status=None):
    """``(SnapshotCapture, None)``, or ``(None, error_code)`` when the app is
    not stamped. *status* is a repo status the caller already has (see
    ``gather_create_data``)."""
    base_version, commit_hash, identity, dirty_states, ver_info, err = (
        gather_create_data(vcs, allow_clean=True, lightweight=True, status=status)
    )
    if err is not None:
        return None, err
    diff_hash = _compute_diff_hash(identity)
    return (
        SnapshotCapture(base_version, commit_hash, identity, dirty_states, ver_info, diff_hash),
        None,
    )


def ensure_code(code_store, vcs, captured):
    """``(code key or None, payload summary)`` for *captured*, storing its code
    object first when *code_store* has no complete one. A clean tree has no
    code to store."""
    if not captured.diff_hash:
        return None, patch_summary(captured.identity)
    key = code_key(captured.code_verstr, captured.diff_hash)
    summary = stored_code(code_store, vcs.name, key)
    if summary is not None:
        publish_code(code_store, vcs.name, key)
        return key, summary
    payload = _with_untracked_payloads(vcs, captured.identity)
    summary = patch_summary(payload)
    store_code(code_store, vcs.name, key, payload, summary)
    return key, summary


def _with_untracked_payloads(vcs, identity):
    """A copy of *identity* plus the untracked tarballs of the repo and its deps."""
    merged = dict(identity)
    if identity.get("deps"):
        merged["deps"] = {path: dict(dep) for path, dep in identity["deps"].items()}
    for dep_path, repo_path in _repos_with_untracked(vcs, identity).items():
        try:
            payload = untracked.untracked_payload(repo_path)
        except Exception:
            VMN_LOGGER.debug("Failed to collect untracked files", exc_info=True)
            continue
        target = merged if dep_path is None else merged["deps"][dep_path]
        target.update(payload)
    return merged


def _repos_with_untracked(vcs, identity):
    """``{dep_path or None: repo_path}`` of the repos that have untracked files."""
    repos = {}
    if identity.get("untracked_hash"):
        repos[None] = vcs.backend.repo_path
    for dep_path, dep in identity.get("deps", {}).items():
        if dep.get("untracked_hash"):
            repos[dep_path] = os.path.join(vcs.vmn_root_path, dep_path)
    return repos
