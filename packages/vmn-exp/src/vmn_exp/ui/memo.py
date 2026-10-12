#!/usr/bin/env python3
"""Small thread-safe memos for the ui's read paths."""
import threading
import time
from collections import OrderedDict


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


def _claim(in_flight_map, key):
    """``(in-flight compute of *key*, whether the caller owns it)``; the
    caller holds the lock guarding *in_flight_map*."""
    in_flight = in_flight_map.get(key)
    if in_flight is not None:
        return in_flight, False
    in_flight = in_flight_map[key] = _InFlight()
    return in_flight, True


def _single_flight(lock, in_flight_map, key, in_flight, compute, keep):
    """The owner's ``compute()``: *keep* its value, then hand it (or its
    exception) to every waiter on *in_flight*."""
    try:
        value = compute()
    except BaseException as exc:  # noqa: BLE001 - relayed to every waiter
        with lock:
            del in_flight_map[key]
        in_flight.finish(None, exc)
        raise
    with lock:
        del in_flight_map[key]
    keep(value)
    in_flight.finish(value, None)
    return value


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

    def peek(self, key):
        """*key*'s value if it is kept, else None; never computes or reorders."""
        with self._lock:
            return self._entries.get(key)

    def put(self, key, value):
        """Keep *value* as *key*'s, the most recently used."""
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)

    def values(self):
        """The kept values, least recently used first."""
        with self._lock:
            return list(self._entries.values())

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
            in_flight, owner = _claim(self._in_flight, key)
        if not owner:
            return in_flight.wait()
        return _single_flight(self._lock, self._in_flight, key, in_flight, compute,
                              lambda value: store(value) and self.put(key, value))

    def per_snapshot(self, snapshot, compute, key=()):
        """``compute()`` once per *snapshot* object (keyed by identity) and *key*."""
        return self.get(
            (id(snapshot),) + tuple(key),
            lambda: (snapshot, compute()),
            valid=lambda hit: hit[0] is snapshot,
        )[1]


class TTLCache:
    """Answers that may be ``ttl_sec`` old; concurrent misses on a key
    single-flight onto one ``compute`` call, like :class:`LRU`'s."""

    def __init__(self, ttl_sec):
        self.ttl_sec = ttl_sec
        self._entries = {}  # key -> (computed at, value)
        self._lock = threading.Lock()
        self._in_flight = {}  # key -> _InFlight, only while a compute runs

    def get(self, key, compute):
        """*key*'s value, computed again once it is ``ttl_sec`` old."""
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and now - hit[0] < self.ttl_sec:
                return hit[1]
            in_flight, owner = _claim(self._in_flight, key)
        if not owner:
            return in_flight.wait()
        return _single_flight(self._lock, self._in_flight, key, in_flight, compute,
                              lambda value: self._keep(key, now, value))

    def _keep(self, key, now, value):
        with self._lock:
            self._entries[key] = (now, value)

    def pop(self, key):
        with self._lock:
            self._entries.pop(key, None)
