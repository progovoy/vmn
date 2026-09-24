#!/usr/bin/env python3
"""In-process cache for the stamp-tree endpoints (``/tree``, ``/tree/root``,
``/deps``), keyed by the app's tag list.

Every tree is a pure function of the app's tags, and those only change when a
version is stamped, so one ``git tag --list`` per request tells whether the
last answer still holds — instead of re-reading and re-parsing every tag.
"""
import hashlib
import subprocess

from version_stamp.core.version_math import app_name_to_tag_name
from version_stamp.ui.memo import LRU

MAX_ENTRIES = 128
UNKNOWN = "error"  # the fingerprint when the tags could not be listed


def versions_fingerprint(root_path, app_name):
    """Cheap staleness signal: the app's tag list (one local git call)."""
    prefix = app_name_to_tag_name(app_name)
    result = subprocess.run(
        ["git", "tag", "--list", f"{prefix}_*"],
        capture_output=True,
        text=True,
        cwd=root_path,
    )
    if result.returncode != 0:
        return UNKNOWN
    return hashlib.sha256(result.stdout.encode()).hexdigest()


class TreeCache:
    def __init__(self, size=MAX_ENTRIES):
        self._entries = LRU(size)  # key -> (fingerprint, value)

    def clear(self):
        self._entries.clear()

    def get(self, root_path, app_name, kind, compute, *args):
        """``compute()``'s value, reused while the app's tags are unchanged."""
        fingerprint = versions_fingerprint(root_path, app_name)
        if fingerprint == UNKNOWN:
            return compute()
        return self._entries.get(
            (root_path, app_name, kind) + args,
            lambda: (fingerprint, compute()),
            valid=lambda hit: hit[0] == fingerprint,
        )[1]


TREES = TreeCache()
