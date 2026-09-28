#!/usr/bin/env python3
"""Which patch kinds a dev-version record holds, for the run detail API."""


# Patch kind -> the metadata flag recording whether the record holds it.
_PATCH_FLAGS = {
    "working_tree": "has_working_tree_patch",
    "local_commits": "has_local_commits_patch",
    "untracked_files": "has_untracked_files",
}


def patch_presence(storage, app_name, verstr, metadata):
    """Which patch kinds a record holds — from its metadata flags.

    Only a legacy record that predates the flags pays for loading the patches
    (the untracked tarball can be hundreds of MB).
    """
    if all(flag in metadata for flag in _PATCH_FLAGS.values()):
        return {kind: bool(metadata[flag]) for kind, flag in _PATCH_FLAGS.items()}
    _, patches = storage.load(app_name, verstr)
    return {kind: bool((patches or {}).get(kind)) for kind in _PATCH_FLAGS}
