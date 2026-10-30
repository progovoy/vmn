#!/usr/bin/env python3
"""One holder per key at a time: a memo's fill single-flights by taking its
key's turn, so a caller arriving while another fills the same key waits for
it, then finds the memo filled (or, after a failure, fills it itself)."""
import threading
from contextlib import contextmanager

from vmn_exp.core.traced_lock import TracedLock


class KeyedLocks:
    """Reentrant locks per key, made on demand and dropped once no thread
    holds or waits on them; different keys never block each other."""

    def __init__(self, name):
        self._name = name
        self._guard = threading.Lock()
        self._locks = {}  # key -> [TracedLock, holders and waiters]

    @contextmanager
    def turn(self, key, blocking=True):
        """Hold *key*'s turn, yielding True; with *blocking* False, yield
        False at once (holding nothing) while another thread holds it."""
        with self._guard:
            entry = self._locks.get(key)
            if entry is None:
                entry = self._locks[key] = [TracedLock(self._name, reentrant=True), 0]
            entry[1] += 1
        lock = entry[0]
        try:
            got = lock.acquire(blocking)
            try:
                yield got
            finally:
                if got:
                    lock.release()
        finally:
            with self._guard:
                entry[1] -= 1
                if not entry[1]:
                    del self._locks[key]
