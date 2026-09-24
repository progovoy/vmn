#!/usr/bin/env python3
"""A tiny time-bounded memo for answers that may be a few seconds old."""
import threading
import time


class TTLCache:
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
