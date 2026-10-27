#!/usr/bin/env python3
"""An app's status summary (:func:`~vmn_exp.ui.status_summary.status_summary`
of the board's non-archived rows), carried across index generations.

Live runs make a new generation about every second, so recounting every row
per generation is O(N) per poll. Here each base's static rows (those no time
bucket changes) are kept as a :class:`StatusTally`, moved on from the app's
last one by the cache's deltas (:class:`~vmn_exp.ui.leaderboard_delta.DeltaLog`):
minus the rows that left, plus the rows that joined — an outer run that ends
moves only its re-settled subtree. The rows a time bucket can change (live
runs and their ancestors) are counted on top per request: O(live). A delta
too large, or a generation the log does not connect, counts the static rows
from scratch. :func:`~vmn_exp.ui.status_summary.status_summary` stays the
from-scratch count the tests hold this one to.
"""
import bisect
import datetime
import threading

from vmn_exp.core.settle import SETTLED, counted_status
from vmn_exp.core.status import FAILED, parse_iso
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.status_summary import RECENT_SEC, STATUSES, summary_payload


def _failed_at(row, status):
    return parse_iso(row.get("finished_at")) if status == FAILED else None


class StatusTally:
    """Rows per counted status (settled ones apart from the statuses) and
    the failed rows' finish times, sorted. Never changed once built."""

    def __init__(self, counts, failed_at):
        self.counts = counts
        self.failed_at = failed_at

    @classmethod
    def of(cls, rows):
        counts, failed_at = dict.fromkeys(STATUSES + SETTLED, 0), []
        for row in rows:
            status = counted_status(row)
            counts[status] += 1
            at = _failed_at(row, status)
            if at is not None:
                failed_at.append(at)
        failed_at.sort()
        return cls(counts, failed_at)

    def moved(self, left, joined):
        """A copy without the *left* rows' contributions, with the *joined*'
        (the finish times copied only when a failed row moves)."""
        counts, failed_at = dict(self.counts), self.failed_at
        for rows, by in ((left, -1), (joined, 1)):
            for row in rows:
                status = counted_status(row)
                counts[status] += by
                at = _failed_at(row, status)
                if at is None:
                    continue
                if failed_at is self.failed_at:
                    failed_at = list(failed_at)
                if by > 0:
                    bisect.insort(failed_at, at)
                else:
                    del failed_at[bisect.bisect_left(failed_at, at)]
        return StatusTally(counts, failed_at)

    def _failed_since(self, since):
        return len(self.failed_at) - bisect.bisect_left(self.failed_at, since)

    def summary(self, now, rows):
        """:func:`status_summary` of this tally's rows and *rows* as of *now*."""
        extra = StatusTally.of(rows)
        counts = {key: n + extra.counts[key] for key, n in self.counts.items()}
        since = now - datetime.timedelta(seconds=RECENT_SEC)
        return summary_payload(
            sum(counts.values()),
            {status: counts[status] for status in STATUSES},
            {settled: counts[settled] for settled in SETTLED},
            self._failed_since(since) + extra._failed_since(since),
        )


class StatusCounts:
    """Per base, its static rows' :class:`StatusTally`; per request, the
    summary with the rows a time bucket changes counted on top."""

    def __init__(self, cache, size=8):
        self._cache = cache
        self._static = cache.generations.track(LRU(size))  # {(base token,): StatusTally}
        self._latest = {}  # {app: (base token, StatusTally)}, the newest counted
        self._lock = threading.Lock()

    def summary(self, snapshot, now):
        base, bucket = self._cache._base(snapshot)
        static = self._static.get((base.token,), lambda: self._counted(base))
        return static.summary(now, visible(base.changed_at(bucket), False))

    def _counted(self, base):
        app = base.snapshot.app_name
        with self._lock:
            last = self._latest.get(app)
        moves = last and self._cache._deltas.since(last[0], base)
        if moves:
            static = last[1].moved(*(visible(rows, False) for rows in moves))
        else:
            changed = set(base.patch.changed)
            static = StatusTally.of(row for i, row in enumerate(base.rows)
                                    if i not in changed and not row.get("archived"))
        with self._lock:
            if app not in self._latest or self._latest[app][0] < base.token:
                self._latest[app] = (base.token, static)
        return static
