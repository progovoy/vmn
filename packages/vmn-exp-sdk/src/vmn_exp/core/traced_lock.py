#!/usr/bin/env python3
"""A drop-in ``threading.Lock`` (``reentrant=True``: ``RLock``) that records
its holder and waiters, so a diagnostic dump names the thread a stuck server
is queued behind (:func:`locks_section`).

An uncontended acquire costs one ``monotonic()`` and two attribute sets on
top of the lock (a release one more ``monotonic()`` for ``max_held_sec``;
~0.4 us a cycle); only a contended one registers its waiter. The holder is
one ``(ident, since)`` tuple so a reader never sees half of it. Every lock is in
a weak registry; stats merge per name (one entry per name, so bounded by the
names used). Reading the registry never takes a traced lock: it copies plain
attributes and dicts, which the GIL (or a free-threaded build's per-object
locks) keeps consistent. Counters may lose an increment when two locks of one
name race, which a diagnostic tolerates.
"""
import itertools
import threading
import weakref
from time import monotonic

_get_ident = threading.get_ident
_STATS = {}  # name -> _Stats
_LIVE = {}  # serial -> weakref of a TracedLock
_SERIAL = itertools.count()


class _Stats:
    __slots__ = ("acquires", "contended", "max_wait", "max_held")

    def __init__(self):
        self.acquires = self.contended = 0
        self.max_wait = self.max_held = 0.0


class TracedLock:
    __slots__ = ("name", "_lock", "_reentrant", "_holder", "_depth", "_waiters",
                 "_stats", "__weakref__")

    def __init__(self, name, reentrant=False):
        self.name = name
        self._lock = threading.Lock()
        self._reentrant = reentrant
        self._holder = None  # (thread ident, monotonic acquired at)
        self._depth = 0
        self._waiters = {}  # thread ident -> (thread name, monotonic since)
        self._stats = _STATS.setdefault(name, _Stats())
        serial = next(_SERIAL)
        _LIVE[serial] = weakref.ref(self, lambda _, serial=serial: _LIVE.pop(serial, None))

    def acquire(self, blocking=True, timeout=-1):
        me = _get_ident()
        holder = self._holder
        if self._reentrant and holder is not None and holder[0] == me:
            self._depth += 1
            return True
        if self._lock.acquire(False):
            self._took(me, monotonic())
            return True
        return self._wait(me, timeout) if blocking else False

    def _wait(self, me, timeout):
        since = monotonic()
        self._waiters[me] = (threading.current_thread().name, since)
        try:
            got = self._lock.acquire(True, timeout)
        finally:
            del self._waiters[me]
        if got:
            now = monotonic()
            stats = self._stats
            stats.contended += 1
            stats.max_wait = max(stats.max_wait, now - since)
            self._took(me, now)
        return got

    def _took(self, me, now):
        self._holder = (me, now)
        self._depth = 1
        self._stats.acquires += 1

    def release(self):
        holder = self._holder
        if self._reentrant:
            if holder is None or holder[0] != _get_ident():
                raise RuntimeError("cannot release un-acquired lock")
            self._depth -= 1
            if self._depth:
                return
        if holder is not None:
            stats = self._stats
            stats.max_held = max(stats.max_held, monotonic() - holder[1])
            self._holder = None
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()

    # -- threading.Condition support -----------------------------------------

    def _is_owned(self):
        holder = self._holder
        return holder is not None and holder[0] == _get_ident()

    def _release_save(self):
        depth = self._depth
        self._depth = 1
        self.release()
        return depth

    def _acquire_restore(self, depth):
        self.acquire()
        self._depth = depth

    def __repr__(self):
        return f"<TracedLock {self.name!r} {'locked' if self.locked() else 'unlocked'}>"

    def _report(self, now, names):
        holder, waiters = self._holder, list(self._waiters.values())
        if holder is None and not waiters:
            return None
        return {
            "name": self.name,
            "holder": None if holder is None else names.get(holder[0], f"thread {holder[0]}"),
            "held_sec": None if holder is None else round(now - holder[1], 4),
            "waiters": [{"thread": thread, "waiting_sec": round(now - since, 4)}
                        for thread, since in sorted(waiters, key=lambda w: w[1])],
        }


def _stats_entry(name, stats):
    return {"name": name, "acquires": stats.acquires, "contended": stats.contended,
            "max_wait_sec": round(stats.max_wait, 4), "max_held_sec": round(stats.max_held, 4)}


def locks_section():
    """``{"held": [{name, holder, held_sec, waiters}], "stats": [...]}``: the
    locks held or waited on now, longest held first, and each name's
    cumulative counts, the longest waits first."""
    now = monotonic()
    names = {t.ident: t.name for t in threading.enumerate()}
    held = []
    for ref in list(_LIVE.values()):
        lock = ref()
        entry = lock and lock._report(now, names)
        if entry:
            held.append(entry)
    held.sort(key=lambda e: -(e["held_sec"] or 0))
    stats = [_stats_entry(name, s) for name, s in list(_STATS.items())]
    stats.sort(key=lambda s: (-s["max_wait_sec"], s["name"]))
    return {"held": held, "stats": stats}
