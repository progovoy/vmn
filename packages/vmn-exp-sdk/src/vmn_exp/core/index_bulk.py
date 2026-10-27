#!/usr/bin/env python3
"""How often an index loading many records at once (a cold remote load)
publishes them.

A remote cold load reads its records newest first, so each chunk of older
records sorts before the ones already loaded: every row's ``idx`` moves and
the next snapshot rebuilds its maps and re-numbers every row, as the store
re-numbers its persisted rows — O(loaded) per chunk. Published every 500
records, a 497k-run load did that ~1000 times: at 13 runs/s it would have
taken ten hours. :class:`BulkPublish` makes the next publish due once the
records loaded since the last one are :data:`PUBLISH_FRACTION` of those
published (and at least a chunk), or once :data:`PUBLISH_EVERY_SEC` — at
least :data:`COST_MULTIPLE` times the last publish's cost — passed: a
constant cost per record however big the store, with the first chunk
published at once and the board moving every few seconds while it is small.
"""
import time

from vmn_exp.core.index_snapshot import IndexSnapshot

PUBLISH_FRACTION = 0.05
PUBLISH_EVERY_SEC = 10.0
COST_MULTIPLE = 20
_monotonic = time.monotonic


class BulkPublish:
    """The changes a bulk load has not published yet, and when it should."""

    def __init__(self):
        self.new, self.touched, self.resort, self.removed = [], set(), False, False
        self._published_at, self._cost = _monotonic(), 0.0

    def add(self, new, removed, redescribed, touched):
        self.new += new
        self.touched |= touched
        self.resort |= bool(redescribed or removed)
        self.removed |= bool(removed)

    def pending(self):
        return bool(self.new or self.touched or self.resort)

    def due(self, published_rows, chunk):
        """Whether to publish now, *published_rows* published so far, a
        load's *chunk* the least worth publishing."""
        if len(self.new) >= max(chunk, PUBLISH_FRACTION * published_rows):
            return True
        every = max(PUBLISH_EVERY_SEC, COST_MULTIPLE * self._cost)
        return self.pending() and _monotonic() - self._published_at >= every

    def take(self):
        """``(new keys, resort, touched or None when a record went)`` to
        publish now (then :meth:`published`)."""
        taken = (self.new, self.resort, None if self.removed else self.touched)
        self.new, self.touched, self.resort, self.removed = [], set(), False, False
        return taken

    def published(self, started):
        """A publish begun at monotonic *started* just ended."""
        now = _monotonic()
        self._published_at, self._cost = now, now - started


def loading_snapshot(app_name, expected):
    """What an index answers before anything is published: no rows, loading
    ``(0, expected)`` (*expected* None while not even the names are listed)."""
    return IndexSnapshot(app_name=app_name, generation=0, rows=(), run_states={}, edges={},
                         loading=(0, expected))
