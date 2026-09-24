#!/usr/bin/env python3
"""The leaderboard pipeline, memoized per index snapshot.

Deriving status, the run tree, filtering and sorting cost O(N) per request —
at 100k runs that is the whole budget. But an :class:`IndexSnapshot` never
changes, so all of it is done once per snapshot (a new one comes with each
index generation) and a page is a slice of the memoized ordering.

Status is time-dependent only while a run is live (no exit code yet: a stale
heartbeat turns ``running`` into ``stuck``). Finished and never-run rows get
their status once per snapshot; live rows are re-derived once per
``bucket_sec`` time bucket, the tree only when a live status actually moved.
Rows handed out are shared: callers must treat them as read-only.
"""
import hashlib
import itertools
import json
import os
import threading

from version_stamp.core import experiment_status
from version_stamp.core.experiment_status import status_fields
from version_stamp.core.experiment_tree import annotate_tree
from version_stamp.ui.http_params import MAX_PAGE
from version_stamp.ui.memo import LRU
from version_stamp.ui.readers.experiments import apply_filters, facets, sort_rows

BUCKET_SEC = 2
# Tokens are per process, so an ETag from before a restart never matches.
_NONCE = os.urandom(8).hex()


def _is_live(run_state):
    return bool(run_state) and run_state.get("exit_code") is None


def _annotated(rows, run_states):
    return annotate_tree(
        {**row, **status_fields(run_states.get(row["verstr"]))} for row in rows
    )


class _Base:
    """One snapshot's rows with their status and tree fields."""

    def __init__(self, snapshot, token, bucket):
        self.snapshot = snapshot
        self.token = token
        states = snapshot.run_states
        self.live = tuple(
            i for i, row in enumerate(snapshot.rows) if _is_live(states.get(row["verstr"]))
        )
        self.rows = _annotated(snapshot.rows, states)
        self._at = (bucket, self.rows)
        self._lock = threading.Lock()

    def rows_at(self, bucket):
        """The rows as of time *bucket* (None: nothing live, always the same)."""
        with self._lock:
            if bucket is not None and self._at[0] != bucket:
                self._at = (bucket, self._rederive_live())
            return self._at[1] if bucket is not None else self.rows

    def _rederive_live(self):
        rows, moved = list(self.rows), False
        states = self.snapshot.run_states
        for i in self.live:
            fields = status_fields(states.get(rows[i]["verstr"]))
            moved = moved or fields["status"] != rows[i]["status"]
            rows[i] = {**rows[i], **fields}
        return annotate_tree(rows) if moved else rows


def _schema_key(schema):
    return json.dumps(schema or {}, sort_keys=True, default=str)


class LeaderboardCache:
    def __init__(self, max_page=MAX_PAGE, bucket_sec=BUCKET_SEC, size=32):
        self.max_page = max_page
        self.bucket_sec = bucket_sec
        self._tokens = itertools.count(1)
        self._bases = LRU(8)
        self._facets = LRU(8)
        self._sorted = LRU(size)

    def _bucket(self):
        return int(experiment_status._now().timestamp() // self.bucket_sec)

    def _base(self, snapshot):
        """``(base, bucket)``; the bucket is None while nothing is live."""
        bucket = self._bucket()
        base = self._bases.per_snapshot(
            snapshot, lambda: _Base(snapshot, next(self._tokens), bucket)
        )
        return base, (bucket if base.live else None)

    def _ordered(self, snapshot, schema, sort, last, status, query, order):
        base, bucket = self._base(snapshot)
        key = (base.token, bucket, _schema_key(schema), sort, last, status, query, order)
        return self._sorted.get(
            key,
            lambda: sort_rows(
                apply_filters(base.rows_at(bucket), status, query),
                schema,
                sort=sort,
                last=last,
                order=order,
            ),
        )

    def page(
        self, snapshot, schema, sort=None, last=None, offset=0, limit=None,
        status=None, query=None, order=None,
    ):
        """What ``leaderboard`` answers for the same arguments, from the memo.

        Without *limit* a plain list of at most ``max_page`` rows; with it
        ``{"rows", "total"}``. Raises ``QueryError`` on a bad *query*.
        """
        rows = self._ordered(snapshot, schema, sort, last, status, query, order)
        offset = offset or 0
        if limit is None:
            return rows[offset : offset + self.max_page]
        return {"rows": rows[offset : offset + limit], "total": len(rows)}

    def etag(self, snapshot, schema, **params):
        """Changes whenever :meth:`page` could answer differently."""
        base, bucket = self._base(snapshot)
        raw = json.dumps(
            [_NONCE, base.token, bucket, _schema_key(schema), sorted(params.items())],
            default=str,
        )
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    def facets(self, snapshot):
        """The app's filter vocabulary, once per snapshot."""
        return self._facets.per_snapshot(snapshot, lambda: facets(snapshot.rows))
