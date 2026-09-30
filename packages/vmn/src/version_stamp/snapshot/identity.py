"""Snapshot identity: record names, diff hashes and dev verstrs.

A leaf module (it imports only ``version_stamp.core``), shared by
:mod:`version_stamp.devversion.capture` and :mod:`version_stamp.snapshot.record`,
which re-export these names.
"""
import hashlib
import os

from version_stamp.core.utils import valid_path_component, yaml_safe_load

# Diff-hash prefix lengths tried, shortest first, when a verstr is taken by a
# snapshot with different content (a 7-hex prefix is only 28 bits).
_DIFF_HASH_LENGTHS = (7, 12, 16, 24, 32, 64)


def safe_verstr(verstr):
    """*verstr* as a record directory name; ValueError if it would walk."""
    if not valid_path_component(verstr):
        raise ValueError(f"Invalid record name: {verstr!r}")
    return verstr.replace("+", "_plus_")


def unsafe_verstr(name):
    return name.replace("_plus_", "+")


def safe_dep_name(dep_path):
    return dep_path.replace(os.sep, "_").replace("/", "_")


def _compute_diff_hash(patches):
    """Full sha256 hex over a snapshot's content, or None for a clean tree."""
    h = hashlib.sha256()
    has_content = False
    for key in ("working_tree", "local_commits"):
        if patches.get(key):
            h.update(patches[key].encode())
            has_content = True
    if patches.get("untracked_hash"):
        h.update(patches["untracked_hash"])
        has_content = True

    for dep_path in sorted(patches.get("deps", {})):
        dp = patches["deps"][dep_path]
        for key in ("working_tree", "local_commits"):
            if dp.get(key):
                h.update(dp[key].encode())
                has_content = True
        if dp.get("untracked_hash"):
            h.update(dp["untracked_hash"])
            has_content = True

    return h.hexdigest() if has_content else None


def _format_dev_verstr(base_version, commit_hash, diff_hash, hash_len=7):
    diff_part = diff_hash[:hash_len] if diff_hash else "0000000"
    return f"{base_version}-dev.{commit_hash[:7]}.{diff_part}"


def _changeset_hashes(changesets):
    return {path: (info or {}).get("hash") for path, info in (changesets or {}).items()}


def same_state(stored_meta, diff_hash, changesets):
    """Whether *stored_meta* records this exact state: the same full diff hash
    and, unless *changesets* is None (a legacy caller), the same repo commits.
    A record without a ``diff_hash`` never matches."""
    if not diff_hash or stored_meta.get("diff_hash") != diff_hash:
        return False
    if changesets is None:
        return True
    return _changeset_hashes(stored_meta.get("changesets")) == _changeset_hashes(changesets)


def _stored_metadata(storage, app_name, verstr):
    """``(exists, metadata dict)`` of the snapshot stored at *verstr*."""
    raw = storage.load_file(app_name, verstr, "metadata.yml")
    if raw is None:
        return False, {}
    try:
        meta = yaml_safe_load(raw)
    except Exception:
        meta = None
    return True, meta if isinstance(meta, dict) else {}


def _unique_snapshot_verstr(
    storage, app_name, base_version, commit_hash, diff_hash, changesets=None
):
    """The shortest dev verstr that is free or already holds this exact state.

    A snapshot never overwrites a different one: on a prefix collision (or a
    legacy record that carries no ``diff_hash`` to compare) the diff hash is
    extended instead. With *changesets*, a record of the same diff at other
    repo commits is a collision too; without them only the diff counts.
    """
    verstr = _format_dev_verstr(base_version, commit_hash, diff_hash)
    if not diff_hash:
        return verstr
    for hash_len in _DIFF_HASH_LENGTHS:
        verstr = _format_dev_verstr(base_version, commit_hash, diff_hash, hash_len)
        exists, stored = _stored_metadata(storage, app_name, verstr)
        if not exists or same_state(stored, diff_hash, changesets):
            return verstr
    return verstr
