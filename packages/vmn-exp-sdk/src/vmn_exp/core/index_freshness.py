#!/usr/bin/env python3
"""How fresh an :mod:`~vmn_exp.core.index` snapshot is, read without I/O or
the index lock (:meth:`ExperimentIndex.freshness`).

``as_of`` is the wall time the last completed refresh started: the store was
listed no earlier than that. It persists in the index store's key-value table
(at most every :data:`PERSIST_EVERY_SEC`), so a restarted process serving its
persisted rows knows they date from its last refresh, not from its start.

While a refresh runs, ``phase`` says what it does — ``full_listing`` (every
record's files), ``journal`` (a journaled sweep's hinted and live records),
``listing`` (another sweep's names-only listing), ``loading_new`` (reading
the records the listing found new or changed) — else ``idle``; ``progress``
(0..1, else None) is how far a full listing's walk is among the index's known
keys (where the storage tells its walk's place, ``listing_position``: S3) or
the share of new records read.
"""
import bisect
import time

FULL_LISTING, JOURNAL, LISTING, LOADING_NEW, IDLE = (
    "full_listing", "journal", "listing", "loading_new", "idle")
PERSIST_EVERY_SEC = 60
_FORMAT = "1"
_wall = time.time


def listing_progress(keys, at):
    """The share of sorted *keys* at or before the walk's place *at*."""
    if not keys or at is None:
        return None
    return round(bisect.bisect_right(keys, at) / len(keys), 3)


class Freshness:
    """One index's ``as_of`` (persisted in ``store()``'s key-value table) and
    refresh phase."""

    def __init__(self, store, app_name):
        self._store, self._scope = store, f"as_of:{app_name}"
        self._as_of = self._persisted_at = self._read_at = self._started = None
        self.phase = IDLE
        self._keys, self._position, self._sorted = None, None, False  # a full listing's
        self._new, self._read = 0, 0  # new records to read, read

    @property
    def as_of(self):
        if self._read_at is None:
            self.load()
        return self._as_of

    def load(self):
        """Read ``as_of`` from the store now."""
        self._read_at = _wall()
        payload = self._store().kv_get(self._scope, _FORMAT)
        self._as_of = self._persisted_at = (payload or {}).get("as_of")

    def reload(self):
        """Read ``as_of`` again when next asked, at most every
        PERSIST_EVERY_SEC (a follower's, which its leader writes)."""
        if self._read_at is not None and _wall() - self._read_at >= PERSIST_EVERY_SEC:
            self._read_at = None

    def started(self):
        """A refresh starts now."""
        self._started = _wall()

    def refreshed(self):
        """The refresh :meth:`started` last completed."""
        wall = self._started
        self._as_of, self._read_at = wall, wall
        if self._persisted_at is None or wall - self._persisted_at >= PERSIST_EVERY_SEC:
            self._store().kv_put(self._scope, _FORMAT, {"as_of": wall})
            self._persisted_at = wall

    def listing(self, phase, keys=(), position=None):
        """A listing of *phase* starts; *position()* tells a full one's place
        among *keys* (copied now, sorted once progress is asked for)."""
        full = phase == FULL_LISTING and position is not None
        self._keys, self._position = (list(keys), position) if full else (None, None)
        self._sorted = False
        self.phase = phase

    def loading(self, new):
        """The refresh reads its *new* records."""
        self._new, self._read, self.phase = new, 0, LOADING_NEW

    def loaded(self, count):
        self._read += count

    def idle(self):
        self._keys = self._position = None
        self.phase = IDLE

    def progress(self):
        if self.phase == LOADING_NEW and self._new:
            return round(min(self._read / self._new, 1.0), 3)
        keys, position = self._keys, self._position
        if keys is None or position is None:
            return None
        if not self._sorted:
            keys.sort()
            self._sorted = True
        return listing_progress(keys, position())

    def state(self, refreshing):
        return {"as_of": self.as_of, "refreshing": refreshing, "phase": self.phase,
                "progress": self.progress()}
