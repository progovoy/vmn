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


class _InFlight:
    """One key's in-progress ``compute()``; late callers wait on it instead of
    calling ``compute`` again."""

    def __init__(self):
        self._done = threading.Event()
        self._value = None
        self._exc = None

    def finish(self, value, exc):
        self._value, self._exc = value, exc
        self._done.set()

    def wait(self):
        self._done.wait()
        if self._exc is not None:
            raise self._exc
        return self._value


class LRU:
    """The *size* most recently used values; *compute* runs outside the lock.

    Concurrent misses on the same key single-flight: only the first caller
    runs ``compute``, the rest block on and reuse its result (or exception).
    Misses on different keys never block each other.
    """

    def __init__(self, size):
        self._size = size
        self._entries = OrderedDict()
        self._lock = threading.Lock()
        self._in_flight = {}  # key -> _InFlight, only while a compute runs

    def clear(self):
        with self._lock:
            self._entries.clear()

    def get(self, key, compute, valid=lambda value: True, store=lambda value: True):
        """*key*'s value; *compute* runs on a miss or when *valid* rejects the
        hit, and its value is kept only when *store* accepts it.

        Concurrent misses on the same key single-flight onto one ``compute``
        call; other keys' misses are unaffected."""
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and valid(hit):
                self._entries.move_to_end(key)
                return hit
            in_flight = self._in_flight.get(key)
            owner = in_flight is None
            if owner:
                in_flight = self._in_flight[key] = _InFlight()
        if not owner:
            return in_flight.wait()
        return self._compute_and_store(key, compute, store, in_flight)

    def _compute_and_store(self, key, compute, store, in_flight):
        try:
            value = compute()
        except BaseException as exc:  # noqa: BLE001 - relayed to every waiter
            with self._lock:
                del self._in_flight[key]
            in_flight.finish(None, exc)
            raise
        with self._lock:
            del self._in_flight[key]
        if store(value):
            with self._lock:
                self._entries[key] = value
                self._entries.move_to_end(key)
                while len(self._entries) > self._size:
                    self._entries.popitem(last=False)
        in_flight.finish(value, None)
        return value

    def per_snapshot(self, snapshot, compute, key=()):
        """``compute()`` once per *snapshot* object (keyed by identity) and *key*."""
        return self.get(
            (id(snapshot),) + tuple(key),
            lambda: (snapshot, compute()),
            valid=lambda hit: hit[0] is snapshot,
        )[1]
