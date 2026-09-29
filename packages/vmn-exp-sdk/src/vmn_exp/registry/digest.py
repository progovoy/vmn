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
    size = files = 0
    for rel, full in _files_below(root):
        manifest.update(f"{rel}\0{sha256_file(full)}\n".encode())
        size += os.path.getsize(full)
        files += 1
    return {"digest": f"sha256:{manifest.hexdigest()}", "size": size, "files": files}


def _files_below(root: str) -> list:
    """``[(posix relpath, path)]`` of every regular file below *root*, relpath-sorted."""
    found = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            if os.path.isfile(full):
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                found.append((rel, full))
    return sorted(found)
