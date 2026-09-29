"""The snapshot record format: file names, record names and metadata fields.

Public:
  - ``METADATA_FILE``, ``PATCH_FILES`` — same as ``vmn_exp.storage.files``.
  - ``safe_verstr(verstr) -> str`` (ValueError if it would leave its dir),
    ``unsafe_verstr(name) -> str``, ``safe_dep_name(dep_path) -> str``.
  - ``skipped_untracked(patches) -> list``, ``patch_summary(patches) -> dict``.
  - ``build_record_metadata(vcs, verstr, base_version, commit_hash,
    dirty_states, patches, ver_info, note=None) -> dict`` — adds
    ``code_verstr`` (the 7-char dev verstr the code object is named by).
  - ``same_state(stored_meta, diff_hash, changesets) -> bool``.
"""
import os

from version_stamp.core.utils import now_iso, valid_path_component
from version_stamp.devversion.capture import _compute_diff_hash, _format_dev_verstr

METADATA_FILE = "metadata.yml"
# (patches key, file name, binary?)
PATCH_FILES = (
    ("working_tree", "working_tree.patch", False),
    ("local_commits", "local_commits.patch", False),
    ("untracked_files", "untracked_files.tar.gz", True),
)


def safe_verstr(verstr):
    """*verstr* as a record directory name; ValueError if it would walk."""
    if not valid_path_component(verstr):
        raise ValueError(f"Invalid record name: {verstr!r}")
    return verstr.replace("+", "_plus_")


def unsafe_verstr(name):
    return name.replace("_plus_", "+")


def safe_dep_name(dep_path):
    return dep_path.replace(os.sep, "_").replace("/", "_")


def skipped_untracked(patches):
    """Untracked paths left out by the size caps, deps prefixed by their path."""
    skipped = list(patches.get("untracked_skipped", []))
    for dep_path, dp in sorted(patches.get("deps", {}).items()):
        skipped.extend(f"{dep_path}/{p}" for p in dp.get("untracked_skipped", []))
    return skipped


def patch_summary(patches):
    """What a record's metadata says about the patches it holds."""
    summary = {
        "has_working_tree_patch": "working_tree" in patches,
        "has_local_commits_patch": "local_commits" in patches,
        "has_untracked_files": "untracked_files" in patches,
        "has_dep_patches": bool(patches.get("deps")),
    }
    skipped = skipped_untracked(patches)
    if skipped:
        summary["untracked_skipped"] = skipped
    return summary


def _remote_url(backend):
    try:
        return backend.remote()
    except Exception:
        return None


def build_record_metadata(
    vcs, verstr, base_version, commit_hash, dirty_states, patches, ver_info, note=None
):
    metadata = {
        "verstr": verstr,
        "base_version": base_version,
        "base_commit": commit_hash,
        "branch": vcs.backend.active_branch,
        "remote": _remote_url(vcs.backend),
        "timestamp": now_iso(),
        "note": note,
        "app_name": vcs.name,
        "dirty_states": dirty_states,
        **patch_summary(patches),
    }
    diff_hash = _compute_diff_hash(patches)
    if diff_hash:
        metadata["diff_hash"] = diff_hash
        metadata["code_verstr"] = _format_dev_verstr(base_version, commit_hash, diff_hash)

    changesets = ver_info["stamping"]["app"].get("changesets", {})
    if changesets:
        metadata["changesets"] = changesets
    return metadata


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
