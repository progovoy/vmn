#!/usr/bin/env python3
"""The leaderboard pipeline, memoized per index snapshot.

Deriving status, the run tree, filtering and sorting cost O(N) per request —
at 100k runs that is the whole budget. But an :class:`IndexSnapshot` never
changes, so all of it is done once per snapshot (a new one comes with each
index generation) and a page is a slice of the memoized ordering.

Status is time-dependent only while a run is live (no exit code yet: a stale
heartbeat turns ``running`` into ``stuck``). Finished and never-run rows get
their status once per snapshot, and each ordering of them is sorted once.
Per ``bucket_sec`` time bucket only the live rows are re-derived, their
ancestors' ``tree_status`` rolled up again, and those few rows re-filtered
and bisected into the cached order (:mod:`~version_stamp.ui.leaderboard_live`)
— O(live · log N), never a full sort. Only ``last`` (a storage-order window
taken after filtering) still re-runs the whole pipeline per bucket.
Rows handed out are shared: callers must treat them as read-only.
"""
import hashlib
import itertools
import json
import os
import threading

from version_stamp.core import experiment_status
from version_stamp.core.experiment_log import primary_metric
from version_stamp.core.experiment_status import status_fields
from version_stamp.core.experiment_tree import annotate_rows
from version_stamp.ui.http_params import MAX_PAGE
from version_stamp.ui.leaderboard_columns import clamp_columns_limit, columns_payload
from version_stamp.ui.leaderboard_live import LivePatch, MergedRows, order_key
from version_stamp.ui.memo import LRU
from version_stamp.ui.readers.experiments import _DESCENDING as DESCENDING
from version_stamp.ui.readers.experiments import apply_filters, facets, sort_rows

BUCKET_SEC = 2
# Tokens are per process, so an ETag from before a restart never matches.
_NONCE = os.urandom(8).hex()


def _is_live(run_state):
    return bool(run_state) and run_state.get("exit_code") is None


def _status(snapshot, verstr):
    """*verstr*'s status fields, judged with the store's write time too."""
    return status_fields(
        snapshot.run_states.get(verstr),
        observed_at=snapshot.run_state_observed_at.get(verstr),
    )


def _visible(rows, archived):
    return rows if archived else [row for row in rows if not row.get("archived")]


def _filtered(rows, status, query, archived):
    return apply_filters(_visible(rows, archived), status, query)


class _Base:
    """One snapshot's rows with their status and tree fields."""

    def __init__(self, snapshot, token, bucket):
        self.snapshot = snapshot
        self.token = token
        states = snapshot.run_states
        live = [
            i for i, row in enumerate(snapshot.rows) if _is_live(states.get(row["verstr"]))
        ]
        self.rows = annotate_rows(
            snapshot.rows, states, snapshot.run_state_observed_at
        )
        self.position = {row["verstr"]: i for i, row in enumerate(self.rows)}
        self.patch = LivePatch(self.rows, live, self.position)
        self._at = (bucket, [self.rows[i] for i in self.patch.changed])
        self._lock = threading.Lock()

    def changed_at(self, bucket):
        """The rows a time bucket can change, as of *bucket*, in storage order."""
        with self._lock:
            if bucket is not None and self._at[0] != bucket:
                self._at = (bucket, self._rederive_live())
            return self._at[1]

    def rows_at(self, bucket):
        """Every row as of time *bucket* — O(N), for what cannot be patched."""
        rows = list(self.rows)
        for i, row in zip(self.patch.changed, self.changed_at(bucket)):
            rows[i] = row
        return rows

    def _rederive_live(self):
        fresh = {
            i: {**self.rows[i], **_status(self.snapshot, self.rows[i]["verstr"])}
            for i in self.patch.live
        }
        return self.patch.rolled_up(self.rows, fresh)


class _Static:
    """One ordering of the rows no time bucket changes, sorted once."""

    def __init__(self, base, schema, sort, status, query, order, archived):
        changed = set(base.patch.changed)
        rows = [row for i, row in enumerate(base.rows) if i not in changed]
        filtered = _filtered(rows, status, query, archived)
        self.sorted = sort_rows(filtered, schema, sort=sort, order=order)
        metric = sort or primary_metric(schema)
        self.has_metric = any(metric in row["metrics"] for row in filtered)
        # Storage order, needed only when live rows alone carry the metric.
        self.filtered = None if self.has_metric else filtered

    def merged(self, base, live, schema, sort, order):
        """This order with the filtered changed rows *live* placed into it."""
        present = lambda m: self.has_metric or any(m in r["metrics"] for r in live)  # noqa: E731
        key, ranked = order_key(schema, sort, DESCENDING.get(order), present, base.position)
        # Ranked by a metric no static row has: they all sort last, in storage order.
        static = self.filtered if ranked and not self.has_metric else self.sorted
        return MergedRows(static, sorted(live, key=key), key)


def _schema_key(schema):
    return json.dumps(schema or {}, sort_keys=True, default=str)


class LeaderboardCache:
    def __init__(self, max_page=MAX_PAGE, bucket_sec=BUCKET_SEC, size=32):
        self.max_page = max_page
        self.bucket_sec = bucket_sec
        self._tokens = itertools.count(1)
        # A snapshot's token identifies it across every app/workspace sharing
        # this cache, so it must never repeat (hence the counter above, not
        # e.g. snapshot.generation, which restarts per app). Keeping it in
        # its own small LRU, separate from the heavy _bases below, means a
        # snapshot recomputed after its _Base was evicted still gets back the
        # token it had before, so its etag stays stable; entries here are a
        # few bytes each, so a larger bound than _bases costs nothing.
        self._base_tokens = LRU(size)
        # Each generation's _Base is a full copy of annotated rows (heavy at
        # 100k+ runs); keep just enough to survive a refresh's old/new
        # snapshot handoff without recomputing for requests straddling it.
        self._bases = LRU(2)
        self._facets = LRU(8)
        self._static = LRU(size)
        self._sorted = LRU(size)
        self._columns = LRU(size)

    def _bucket(self):
        return int(experiment_status._now().timestamp() // self.bucket_sec)

    def _base(self, snapshot):
        """``(base, bucket)``; the bucket is None while nothing is live."""
        bucket = self._bucket()
        token = self._base_tokens.per_snapshot(snapshot, lambda: next(self._tokens))
        base = self._bases.per_snapshot(snapshot, lambda: _Base(snapshot, token, bucket))
        return base, (bucket if base.patch.live else None)

    def _ordered(self, snapshot, schema, sort, last, status, query, order, archived=False):
        base, bucket = self._base(snapshot)
        schema_key = _schema_key(schema)
        filters = (sort, status, query, order, archived)
        if last:
            return self._sorted.get(
                (base.token, bucket, schema_key, last) + filters,
                lambda: sort_rows(
                    _filtered(base.rows_at(bucket), status, query, archived),
                    schema, sort=sort, last=last, order=order,
                ),
            )
        static = self._static.get(
            (base.token, schema_key) + filters,
            lambda: _Static(base, schema, sort, status, query, order, archived),
        )
        if not base.patch.changed:
            return static.sorted
        return self._sorted.get(
            (base.token, bucket, schema_key, None) + filters,
            lambda: static.merged(
                base, _filtered(base.changed_at(bucket), status, query, archived),
                schema, sort, order,
            ),
        )

    def page(
        self, snapshot, schema, sort=None, last=None, offset=0, limit=None,
        status=None, query=None, order=None, archived=False,
    ):
        """What ``leaderboard`` answers for the same arguments, from the memo.

        Without *limit* a plain list of at most ``max_page`` rows; with it
        ``{"rows", "total"}``. Archived rows are left out unless *archived*.
        Raises ``QueryError`` on a bad *query*.
        """
        rows = self._ordered(snapshot, schema, sort, last, status, query, order, archived)
        offset = offset or 0
        if limit is None:
            return rows[offset : offset + self.max_page]
        return {"rows": rows[offset : offset + limit], "total": len(rows)}

    def columns(
        self, snapshot, schema, keys, limit=None, sort=None, status=None,
        query=None, order=None, archived=False,
    ):
        """``{verstrs, idx, columns, total}`` over the first *limit* ordered rows.

        Raises ``ValueError`` on an unknown key, ``QueryError`` on a bad *query*.
        """
        limit = clamp_columns_limit(limit)
        keys = tuple(keys)
        base, bucket = self._base(snapshot)
        params = (sort, status, query, order, archived, keys, limit)
        return self._columns.get(
            (base.token, bucket, _schema_key(schema)) + params,
            lambda: self._columns_payload(snapshot, schema, *params),
        )

    def _columns_payload(self, snapshot, schema, sort, status, query, order, archived, keys, limit):
        rows = self._ordered(snapshot, schema, sort, None, status, query, order, archived)
        return columns_payload(rows[:limit], keys, len(rows))

    def etag(self, snapshot, schema, **params):
        """Changes whenever :meth:`page` could answer differently."""
        base, bucket = self._base(snapshot)
        raw = json.dumps(
            [_NONCE, base.token, bucket, _schema_key(schema), sorted(params.items())],
            default=str,
        )
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    def facets(self, snapshot, archived=False):
        """The app's filter vocabulary, once per snapshot (archived rows only
        when *archived*)."""
        return self._facets.per_snapshot(
            snapshot, lambda: facets(_visible(snapshot.rows, archived)), key=(bool(archived),)
        )
