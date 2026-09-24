#!/usr/bin/env python3
"""In-process cache for the stamp-tree endpoints (``/tree``, ``/tree/root``,
``/deps``), keyed by the app's tag list.

Every tree is a pure function of the app's tags, and those only change when a
version is stamped, so one ``git tag --list`` per request tells whether the
last answer still holds — instead of re-reading and re-parsing every tag.
"""
import threading
from collections import OrderedDict

from version_stamp.ui.index import _versions_fingerprint

MAX_ENTRIES = 128
UNKNOWN = "error"  # the fingerprint when the tags could not be listed


class TreeCache:
    def __init__(self, size=MAX_ENTRIES):
        self._size = size
        self._entries = OrderedDict()  # key -> (fingerprint, value)
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._entries.clear()

    def get(self, root_path, app_name, kind, compute, *args):
        """``compute()``'s value, reused while the app's tags are unchanged."""
        fingerprint = _versions_fingerprint(root_path, app_name)
        if fingerprint == UNKNOWN:
            return compute()
        key = (root_path, app_name, kind) + args
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and hit[0] == fingerprint:
                self._entries.move_to_end(key)
                return hit[1]
        value = compute()
        with self._lock:
            self._entries[key] = (fingerprint, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)
        return value


TREES = TreeCache()
