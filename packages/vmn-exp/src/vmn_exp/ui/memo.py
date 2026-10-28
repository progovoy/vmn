#!/usr/bin/env python3
"""Small thread-safe memos for the ui's read paths."""
import threading
import time
import weakref
from collections import OrderedDict

from vmn_exp.core.traced_lock import TracedLock


class _InFlight:
    """One key's in-progress ``compute()``; late callers wait on it instead of
    calling ``compute`` again."""

    def __init__(self):
        self._done = threading.Event()
        self._value = None
        self._exc = None
        self.overdue = False  # a bounded wait on it ran out

    def done(self, timeout):
        """Whether it finished within *timeout* seconds (once a bounded wait
        ran out, at once: one request per build pays the bound, not each)."""
        if self.overdue:
            return self._done.is_set()
        self.overdue = not self._done.wait(timeout)
        return not self.overdue

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


def _await(in_flight, wait_sec, stale):
    """*in_flight*'s value; past *wait_sec* ``stale()`` instead, unless it
    is None (nothing to answer from: wait on)."""
    if stale is not None and not in_flight.done(wait_sec):
        value = stale()
        if value is not None:
            return value
    return in_flight.wait()


def _single_flight(lock, in_flight_map, key, in_flight, compute, keep):
    """The owner's ``compute()``: *keep* its value, then hand it (or its
    exception) to every waiter on *in_flight*."""
    try:
        value = compute()
    except BaseException as exc:
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

    def __init__(self, size, name="memo"):
        self._size = size
        self._entries = OrderedDict()
        self._lock = TracedLock(name)
        self._in_flight = {}  # key -> _InFlight, only while a compute runs

    def clear(self):
        with self._lock:
            self._entries.clear()

    def drop_where(self, predicate):
        """Forget every kept entry whose key *predicate* accepts."""
        with self._lock:
            for key in [key for key in self._entries if predicate(key)]:
                del self._entries[key]

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

    def get(self, key, compute, valid=lambda value: True, store=lambda value: True,
            stale=None, wait_sec=None):
        """*key*'s value; *compute* runs on a miss or when *valid* rejects the
        hit, and its value is kept only when *store* accepts it.

        Concurrent misses on the same key single-flight onto one ``compute``
        call; other keys' misses are unaffected. A caller waiting on another's
        ``compute`` for over *wait_sec* gets ``stale()`` instead, when that is
        not None."""
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and valid(hit):
                self._entries.move_to_end(key)
                return hit
            in_flight, owner = _claim(self._in_flight, key)
        if not owner:
            return _await(in_flight, wait_sec, stale)
        return _single_flight(self._lock, self._in_flight, key, in_flight, compute,
                              lambda value: store(value) and self.put(key, value))

    def per_snapshot(self, snapshot, compute, key=(), stale=None, wait_sec=None):
        """``compute()`` once per *snapshot* object (keyed by identity) and
        *key*. The entry holds an index snapshot weakly, so it never keeps an
        old generation alive; a dead or reused id fails the identity check.
        *stale*, *wait_sec*: as :meth:`get`'s."""
        return self.get(
            (id(snapshot),) + tuple(key),
            lambda: (_ref(snapshot), compute()),
            valid=lambda hit: hit[0]() is snapshot,
            stale=stale and (lambda: _stale_entry(stale)),
            wait_sec=wait_sec,
        )[1]


class GroupedLRU(LRU):
    """An :class:`LRU` keeping at most *per_group* entries of each group
    (``group_of(value)``) and *groups* groups, least recent leaving first:
    one busy group never evicts the others' entries."""

    def __init__(self, per_group, groups, group_of, name="memo"):
        super().__init__(per_group * groups, name)
        self._per_group, self._groups, self._group_of = per_group, groups, group_of

    def put(self, key, value):
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            group = self._group_of(value)
            mine = [k for k, v in self._entries.items() if self._group_of(v) == group]
            for k in mine[:-self._per_group]:
                del self._entries[k]
            while len({self._group_of(v) for v in self._entries.values()}) > self._groups:
                self._entries.popitem(last=False)


def _stale_entry(stale):
    value = stale()
    return None if value is None else (None, value)


def _ref(obj):
    """A weak reference to *obj*, else (a plain dict or list) a strong one."""
    try:
        return weakref.ref(obj)
    except TypeError:
        return lambda: obj


class Generations:
    """Each app's newest *keep* base tokens. Caches registered with
    :meth:`track` are keyed by a token first (alone or heading a tuple); as
    an app advances, its older generations' entries leave them all."""

    def __init__(self, keep):
        self._keep = keep
        self._newest = {}  # app -> its newest tokens, oldest first
        self._caches = []
        self._lock = TracedLock("memo generations")

    def track(self, lru):
        self._caches.append(lru)
        return lru

    def advance(self, app, token):
        """*token* is *app*'s newest generation; tokens only count up, so an
        older one (an evicted base rebuilt for a held snapshot) changes nothing."""
        with self._lock:
            tokens = self._newest.setdefault(app, [])
            if tokens and token <= tokens[-1]:
                return
            tokens.append(token)
            retired = set(tokens[:-self._keep])
            del tokens[:-self._keep]
        if retired:
            for lru in self._caches:
                lru.drop_where(lambda key: _token_of(key) in retired)


def _token_of(key):
    return key[0] if isinstance(key, tuple) and key else key


class TTLCache:
    """Answers that may be ``ttl_sec`` old; concurrent misses on a key
    single-flight onto one ``compute`` call, like :class:`LRU`'s."""

    def __init__(self, ttl_sec):
        self.ttl_sec = ttl_sec
        self._entries = {}  # key -> (computed at, value)
        self._lock = TracedLock("memo ttl")
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
