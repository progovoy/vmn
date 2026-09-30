"""The snapshot record format: file names, record names and metadata fields.

Public:
  - ``METADATA_FILE``, ``PATCH_FILES`` — same as ``vmn_exp.storage.files``.
  - ``safe_verstr(verstr) -> str`` (ValueError if it would leave its dir),
    ``unsafe_verstr(name) -> str``, ``safe_dep_name(dep_path) -> str``.
  - ``skipped_untracked(patches) -> list``, ``patch_summary(patches) -> dict``.
  - ``build_record_metadata(vcs, verstr, base_version, commit_hash,
    dirty_states, patches, ver_info, note=None, code=None, diff_hash=None)
    -> dict`` — adds ``code_verstr`` (the 7-char dev verstr the code object is
    named by) and, with *code* ``(key, summary)``, the ``code:`` reference.
  - ``same_state(stored_meta, diff_hash, changesets, dep_bases=None) -> bool``.
"""
from version_stamp.core.utils import now_iso
from version_stamp.snapshot.identity import (  # noqa: F401  (public names re-exported)
    _compute_diff_hash,
    _format_dev_verstr,
    safe_dep_name,
    safe_verstr,
    same_state,
    unsafe_verstr,
)

METADATA_FILE = "metadata.yml"
# (patches key, file name, binary?)
PATCH_FILES = (
    ("working_tree", "working_tree.patch", False),
    ("local_commits", "local_commits.patch", False),
    ("untracked_files", "untracked_files.tar.gz", True),
)


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
    vcs, verstr, base_version, commit_hash, dirty_states, patches, ver_info,
    note=None, code=None, diff_hash=None,
):
    """*diff_hash* is hashed from *patches* unless given; *code* is
    ``ensure_code``'s ``(key, summary)`` of the stored code object."""
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
    if code:
        metadata.update(code[1])
    if diff_hash is None:
        diff_hash = _compute_diff_hash(patches)
    if diff_hash:
        metadata["diff_hash"] = diff_hash
        metadata["code_verstr"] = _format_dev_verstr(base_version, commit_hash, diff_hash)

    changesets = ver_info["stamping"]["app"].get("changesets", {})
    if changesets:
        metadata["changesets"] = changesets
    if patches.get("dep_base_commits"):
        metadata["dep_base_commits"] = patches["dep_base_commits"]
    if code and code[0]:
        metadata["code"] = code[0]
    return metadata
