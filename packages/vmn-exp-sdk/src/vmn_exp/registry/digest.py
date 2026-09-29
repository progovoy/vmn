"""Content digests of local files and directories, for reference datasets.

A file's digest is its ``sha256``. A directory's is the sha256 of a manifest
of every file below it, sorted by relative path::

    <relpath>\\0<file sha256 hex>\\n

so it depends on names and contents only — not on mtimes or the order the
filesystem lists them in. Both are ``sha256:<hex>``, the form run outputs use,
so a registered file digest matches the artifact it was logged as.
"""
from __future__ import annotations

import hashlib
import os

from vmn_exp._base import sha256_file
from vmn_exp.storage.files import artifact_file_path, list_artifact_tree


def local_digest(path: str) -> dict:
    """``{"digest", "size", "files"}`` of the file or directory at *path*."""
    if os.path.isdir(path):
        return _dir_digest(path)
    return {
        "digest": f"sha256:{sha256_file(path)}",
        "size": os.path.getsize(path),
        "files": 1,
    }


def _dir_digest(root: str) -> dict:
    manifest = hashlib.sha256()
    tree = list_artifact_tree(root)  # posix relpaths, name-sorted
    for entry in tree:
        file_sha = sha256_file(artifact_file_path(root, entry["name"]))
        manifest.update(f"{entry['name']}\0{file_sha}\n".encode())
    return {
        "digest": f"sha256:{manifest.hexdigest()}",
        "size": sum(entry["size"] for entry in tree),
        "files": len(tree),
    }
