#!/usr/bin/env python3
"""The leaderboard pipeline, memoized per index snapshot and carried across
index generations.

Deriving status, the run tree, filtering and sorting cost O(N) per request —
at 100k runs that is the whole budget. But an :class:`IndexSnapshot` never
changes, so all of it is done once per snapshot and a page is a slice of the
memoized ordering.

A new index generation (about one a second under a live fleet) is not paid
for from scratch either: its base is derived from the previous generation's
(:meth:`_Base.derived`). Rows found changed by identity, plus the live ones,
get their status again; only they, their parents and ancestors get their
tree fields again (:mod:`~vmn_exp.ui.leaderboard_tree`); each cached
ordering drops the rows that left and bisects the new ones in
(:meth:`_Static.advanced`); facet counts move by the same rows
(:mod:`~vmn_exp.ui.leaderboard_facets`). A large delta, a repeated verstr
or a parent cycle falls back to a full rebuild. Non-live rows keep the
time-relative fields (``stale_sec``, ``duration_sec``) of when their record
last changed, as they always did within one snapshot.

Status is time-dependent only while a run is live (no exit code yet: a stale
heartbeat turns ``running`` into ``stuck``). Finished and never-run rows get
their status when their record last changed. Per ``bucket_sec`` time bucket
only the live rows are re-derived, their ancestors' ``tree_status`` rolled
up again, and those few rows re-filtered and bisected into the cached order
(:mod:`~vmn_exp.ui.leaderboard_live`) — O(live · log N), never a full sort.
``last`` (a storage-order window taken after filtering) scans back from the
newest row only as far as it needs. Rows handed out are shared: callers must
treat them as read-only.
"""
import hashlib
import itertools
import json
import os
import threading

import vmn_exp.core.status as experiment_status
from vmn_exp.core.importance import param_importance, require_metric
from vmn_exp.core.log import primary_metric
from vmn_exp.core.status import status_fields
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui.http_params import MAX_PAGE
from vmn_exp.ui.leaderboard_columns import clamp_columns_limit, columns_payload
from vmn_exp.ui.leaderboard_delta import DeltaLog, moved, row_delta, static_moves
from vmn_exp.ui.leaderboard_facets import Facets
from vmn_exp.ui.leaderboard_facets import visible as _visible
from vmn_exp.ui.leaderboard_live import LivePatch, MergedRows, order_key
from vmn_exp.ui.leaderboard_tree import derive_tree, tree_index
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING
from vmn_exp.ui.readers.experiments import apply_filters, sort_rows

BUCKET_SEC = 2
# Orders moved on across generations: the dashboard's mix of sorts and
# queries at 100k rows, each a list of row references.
LATEST_ORDERS = 64
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


def _filtered(rows, status, query, archived):
    return apply_filters(_visible(rows, archived), status, query)


class _Base:
    """One snapshot's rows with their status and tree fields."""

    def __init__(self, snapshot, token, bucket, rows, position, patch, tree):
        self.snapshot = snapshot
        self.token = token
        self.rows = rows
        self.position = position
        self.patch = patch
        self.children_of, self.child_statuses = tree
        # (previous base's token, static rows that left, static rows that joined)
        self.delta = None
        self._at = (bucket, [rows[i] for i in patch.changed])
        self._lock = threading.Lock()

    @classmethod
    def build(cls, snapshot, token, bucket):
        """From scratch: O(N)."""
        states = snapshot.run_states
        live = [i for i, row in enumerate(snapshot.rows) if _is_live(states.get(row["verstr"]))]
        rows = annotate_rows(snapshot.rows, states, snapshot.run_state_observed_at)
        position = {row["verstr"]: i for i, row in enumerate(rows)}
        patch = LivePatch.of_rows(rows, live, position)
        return cls(snapshot, token, bucket, rows, position, patch, tree_index(rows))

    @classmethod
    def derived(cls, prev, snapshot, token, bucket):
        """From *prev*'s base, re-deriving only what changed; None when the
        delta is large, a verstr repeats or a parent chain loops."""
        delta = row_delta(prev, snapshot)
        if delta is None:
            return None
        fresh_at, gone = delta
        position = dict(prev.position)
        for verstr in gone:
            del position[verstr]
        fresh = {}
        for i in fresh_at:
            verstr = snapshot.rows[i]["verstr"]
            position[verstr] = i
            fresh[verstr] = dict(snapshot.rows[i], **_status(snapshot, verstr))
        tree = derive_tree(prev, snapshot, fresh, gone, position)
        if tree is None:
            return None
        rows, children_of, counts, rebuilt = tree
        live = sorted(position[v] for v in fresh if _is_live(snapshot.run_states.get(v)))
        patch = LivePatch.from_counts(rows, live, position, snapshot.edges, counts)
        base = cls(snapshot, token, bucket, rows, position, patch, (children_of, counts))
        base.delta = (prev.token,) + static_moves(prev, base, rebuilt | gone)
        return base

    def changed_at(self, bucket):
        """The rows a time bucket can change, as of *bucket*, in storage order."""
        with self._lock:
            if bucket is not None and self._at[0] != bucket:
                self._at = (bucket, self._rederive_live())
            return self._at[1]

    def tail(self, bucket, count, status, query, archived):
        """The last *count* rows passing the filters (every one when *count*
        < 1) in storage order, as of *bucket*: scans back only as needed."""
        patched = dict(zip(self.patch.changed, self.changed_at(bucket)))
        out, stop, chunk = [], len(self.rows), max(count, 64)
        while stop and (count < 1 or len(out) < count):
            start = max(0, stop - chunk)
            window = [patched.get(i, self.rows[i]) for i in range(start, stop)]
            out = _filtered(window, status, query, archived) + out
            stop, chunk = start, chunk * 2
        return out

    def _rederive_live(self):
        fresh = {
            i: {**self.rows[i], **_status(self.snapshot, self.rows[i]["verstr"])}
            for i in self.patch.live
        }
        return self.patch.rolled_up(self.rows, fresh)


def _carrying(metric, rows):
    return sum(1 for row in rows if metric in row["metrics"])


def _by_position(position):
    return lambda row: position[row["verstr"]]


class _Static:
    """One ordering of the rows no time bucket changes."""

    def __init__(self, token, ordered, filtered, with_metric):
        self.token = token  # of the base this order was built or moved for
        self.sorted = ordered
        self.with_metric = with_metric  # rows carrying the sort metric
        self.has_metric = bool(with_metric)
        # Storage order, needed only when live rows alone carry the metric.
        self.filtered = None if with_metric else filtered

    @classmethod
    def build(cls, base, schema, sort, status, query, order, archived):
        """Filtered and sorted from scratch: O(N log N)."""
        changed = set(base.patch.changed)
        rows = [row for i, row in enumerate(base.rows) if i not in changed]
        filtered = _filtered(rows, status, query, archived)
        ordered = sort_rows(filtered, schema, sort=sort, order=order)
        with_metric = _carrying(sort or primary_metric(schema), filtered)
        return cls(base.token, ordered, filtered, with_metric)

    def advanced(self, base, left, joined, schema, sort, status, query, order, archived):
        """This order moved to *base*: the *left* rows out (by identity, so
        from any number of generations back), the *joined* rows in by
        bisection. None when whether any row carries the sort metric flips —
        the order changes shape then — or a left row is missing."""
        left = _filtered(left, status, query, archived)
        joined = _filtered(joined, status, query, archived)
        metric = sort or primary_metric(schema)
        with_metric = self.with_metric - _carrying(metric, left) + _carrying(metric, joined)
        if bool(with_metric) != self.has_metric:
            return None
        key = order_key(schema, sort, DESCENDING.get(order), lambda m: self.has_metric,
                        base.position)[0]
        ordered = moved(self.sorted, left, joined, key)
        filtered = None
        if not with_metric:
            filtered = moved(self.filtered, left, joined, _by_position(base.position))
        if ordered is None or (filtered is None and not with_metric):
            return None
        return _Static(base.token, ordered, filtered, with_metric)

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
        # snapshot handoff, and to derive the next generation from.
        self._bases = LRU(2)
        self._facets = Facets()
        self._static = LRU(size)
        self._latest = LRU(LATEST_ORDERS)  # (schema, filters) -> newest _Static
        self._deltas = DeltaLog()
        self._sorted = LRU(size)
        self._columns = LRU(size)
        self._importance = LRU(size)

    def _bucket(self):
        return int(experiment_status._now().timestamp() // self.bucket_sec)

    def _base(self, snapshot):
        """``(base, bucket)``; the bucket is None while nothing is live."""
        bucket = self._bucket()
        token = self._base_tokens.per_snapshot(snapshot, lambda: next(self._tokens))
        base = self._bases.per_snapshot(snapshot, lambda: self._new_base(snapshot, token, bucket))
        return base, (bucket if base.patch.live else None)

    def _new_base(self, snapshot, token, bucket):
        """Derived from the app's latest kept base, else built. Any base is a
        valid start (even another workspace's): the delta is found by identity."""
        kept = [base for snap, base in self._bases.values() if snap.app_name == snapshot.app_name]
        prev = max(kept, key=lambda base: base.token, default=None)
        derived = prev and _Base.derived(prev, snapshot, token, bucket)
        if derived:
            self._deltas.add(derived)
        return derived or _Base.build(snapshot, token, bucket)

    def _ordered(self, snapshot, schema, sort, last, status, query, order, archived=False):
        base, bucket = self._base(snapshot)
        schema_key = _schema_key(schema)
        filters = (sort, status, query, order, archived)
        if last:
            return self._sorted.get(
                (base.token, bucket, schema_key, last) + filters,
                lambda: sort_rows(
                    base.tail(bucket, int(last), status, query, archived),
                    schema, sort=sort, last=last, order=order,
                ),
            )
        static = self._static.get(
            (base.token, schema_key) + filters,
            lambda: self._static_of(base, schema_key, schema, filters),
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

    def _static_of(self, base, schema_key, schema, filters):
        """Moved on from the last generation this order was served in, across
        the deltas since (the dashboard asks for many orders, each only now
        and then); built when that is too far back or too much changed."""
        key = (schema_key,) + filters
        last = self._latest.peek(key)
        moves = last and self._deltas.since(last.token, base)
        static = moves and last.advanced(base, *moves, schema, *filters)
        static = static or _Static.build(base, schema, *filters)
        self._latest.put(key, static)
        return static

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

    def importance(self, snapshot, schema, metric, status=None, query=None, archived=False):
        """Parameter importance for *metric* over the filtered rows.

        Raises ``ValueError`` when no visible run carries *metric*,
        ``QueryError`` on a bad *query*.
        """
        base, bucket = self._base(snapshot)
        params = (metric, status, query, archived)
        return self._importance.get(
            (base.token, bucket, _schema_key(schema)) + params,
            lambda: self._importance_payload(snapshot, schema, *params),
        )

    def _importance_payload(self, snapshot, schema, metric, status, query, archived):
        require_metric(self._ordered(snapshot, schema, None, None, None, None, None, archived), metric)
        rows = self._ordered(snapshot, schema, None, None, status, query, None, archived)
        return param_importance(rows, metric)

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
        when *archived*), moved on from the app's last counts."""
        return self._facets.get(snapshot, archived)
