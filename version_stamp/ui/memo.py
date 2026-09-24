#!/usr/bin/env python3
"""Small thread-safe memos for the ui's read paths."""
import threading
import time
from collections import OrderedDict


class TTLCache:
    """Answers that may be ``ttl_sec`` old."""

    def __init__(self, ttl_sec):
        self.ttl_sec = ttl_sec
        self._entries = {}  # key -> (computed at, value)
        self._lock = threading.Lock()

    def get(self, key, compute):
        """*key*'s value, computed again once it is ``ttl_sec`` old."""
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
        if hit is not None and now - hit[0] < self.ttl_sec:
            return hit[1]
        value = compute()
        with self._lock:
            self._entries[key] = (now, value)
        return value

    def pop(self, key):
        with self._lock:
            self._entries.pop(key, None)


class LRU:
    """The *size* most recently used values; *compute* runs outside the lock."""

    def __init__(self, size):
        self._size = size
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._entries.clear()

    def get(self, key, compute, valid=lambda value: True, store=lambda value: True):
        """*key*'s value; *compute* runs on a miss or when *valid* rejects the
        hit, and its value is kept only when *store* accepts it."""
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and valid(hit):
                self._entries.move_to_end(key)
                return hit
        value = compute()
        if not store(value):
            return value
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)
        return value

    def per_snapshot(self, snapshot, compute, key=()):
        """``compute()`` once per *snapshot* object (keyed by identity) and *key*."""
        return self.get(
            (id(snapshot),) + tuple(key),
            lambda: (snapshot, compute()),
            valid=lambda hit: hit[0] is snapshot,
        )[1]
