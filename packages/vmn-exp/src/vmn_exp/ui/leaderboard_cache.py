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
newest row only as far as it needs. Scope and top (plan 23 S2) are filters
like the others (:mod:`~vmn_exp.ui.leaderboard_scope`), a scoped order built
from the subtree alone; ``job:*`` orders are :mod:`~vmn_exp.ui.leaderboard_jobs`.
Rows handed out are shared: callers must treat them as read-only.
"""
import hashlib
import itertools
import json
import os
import threading

import vmn_exp.core.status as experiment_status
from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core.log import primary_metric
from vmn_exp.core.query import parse_query
from vmn_exp.core.status import status_fields
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui.failure_signature import signed
from vmn_exp.ui.http_params import MAX_PAGE
from vmn_exp.ui.job_rollup_cache import JobRollupCache
from vmn_exp.ui.leaderboard_answers import IMPORTANCE_RESULTS, SetAnswers
from vmn_exp.ui.leaderboard_columns import clamp_columns_limit, columns_payload
from vmn_exp.ui.leaderboard_cursor import Pager, fingerprint, keyed
from vmn_exp.ui.leaderboard_delta import DeltaLog, moved, row_delta, static_moves
from vmn_exp.ui.leaderboard_facets import Facets
from vmn_exp.ui.leaderboard_group_cache import GroupCache
from vmn_exp.ui.leaderboard_jobs import JobsView
from vmn_exp.ui.leaderboard_live import LivePatch, MergedRows, order_key
from vmn_exp.ui.leaderboard_scope import (
    Filters,
    check_scope,
    filtered,
    left_filtered,
    scope_positions,
)
from vmn_exp.ui.leaderboard_subtree_match import SubtreeMatch
from vmn_exp.ui.leaderboard_top_counts import TopCounts
from vmn_exp.ui.leaderboard_tree import derive_tree, tree_index
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING
from vmn_exp.ui.readers.experiments import sort_rows
from vmn_exp.ui.search_index import SearchIndexes
from vmn_exp.ui.search_rank import results

from vmn_exp.ui import search_prefilter

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


def _restated(snapshot, row):
    """A copy of *row* with its status fields as of now."""
    return signed({**row, **_status(snapshot, row["verstr"])})


class _Base:
    """One snapshot's rows with their status and tree fields."""

    def __init__(self, snapshot, token, bucket, rows, position, patch, tree):
        self.snapshot = snapshot
        self.token = token
        self.rows = rows
        self.position = position
        self.patch = patch
        self.children_of, self.child_statuses = tree
        self.scopes = {}  # {scope: storage indexes of its subtree}
        # (previous base's token, static rows that left, static rows that joined)
        self.delta = None
        self._at = (bucket, [rows[i] for i in patch.changed])
        self._patched = (None, None)  # (changed_at's rows, patched() of them)
        self._lock = threading.Lock()

    @classmethod
    def build(cls, snapshot, token, bucket):
        """From scratch: O(N) — a copy of every row, so with collection
        paused (see :mod:`~vmn_exp.core.gc_pause`)."""
        states = snapshot.run_states
        with gc_paused():
            live = [i for i, row in enumerate(snapshot.rows)
                    if _is_live(states.get(row["verstr"]))]
            rows = [signed(row) for row in
                    annotate_rows(snapshot.rows, states, snapshot.run_state_observed_at)]
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
            fresh[verstr] = _restated(snapshot, snapshot.rows[i])
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

    def patched(self, bucket):
        """``{storage index: row as of *bucket*}`` of the rows a time bucket
        can change, built once per bucket."""
        rows = self.changed_at(bucket)
        with self._lock:
            if self._patched[0] is not rows:
                self._patched = (rows, dict(zip(self.patch.changed, rows)))
            return self._patched[1]

    def tail(self, bucket, count, f):
        """The last *count* rows passing the :class:`Filters` *f* (every one
        when *count* < 1) in storage order, as of *bucket*: scans back only
        as needed, within the scope's subtree when *f* has one."""
        patched = self.patched(bucket)
        at = scope_positions(self, f.scope) if f.scope else range(len(self.rows))
        out, stop, chunk = [], len(at), max(count, 64)
        while stop and (count < 1 or len(out) < count):
            start = max(0, stop - chunk)
            window = [patched.get(i, self.rows[i]) for i in at[start:stop]]
            out = filtered(self.snapshot, window, f) + out
            stop, chunk = start, chunk * 2
        return out

    def _rederive_live(self):
        fresh = {i: _restated(self.snapshot, self.rows[i]) for i in self.patch.live}
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
    def build(cls, base, schema, f, slots=None):
        """Filtered (:class:`Filters` *f*) and sorted from scratch: O(N log N),
        N the scope's subtree when *f* has one. *slots*: the storage slots
        that may pass *f*'s query (None: every one)."""
        changed = set(base.patch.changed)
        at = scope_positions(base, f.scope) if f.scope else range(len(base.rows))
        if slots is not None:
            at = sorted(set(at) & slots) if f.scope else sorted(slots)
        rows = [base.rows[i] for i in at if i not in changed]
        kept = filtered(base.snapshot, rows, f)
        ordered = sort_rows(kept, schema, sort=f.sort, order=f.order)
        with_metric = _carrying(f.sort or primary_metric(schema), kept)
        return cls(base.token, ordered, kept, with_metric)

    def advanced(self, base, left, joined, schema, f):
        """This order moved to *base*: the *left* rows out (by identity, so
        from any number of generations back), the *joined* rows in by
        bisection. None when whether any row carries the sort metric flips —
        the order changes shape then — or a left row is missing."""
        left = left_filtered(self.sorted, left, f)
        joined = filtered(base.snapshot, joined, f)
        sort, order = f.sort, f.order
        metric = sort or primary_metric(schema)
        with_metric = self.with_metric - _carrying(metric, left) + _carrying(metric, joined)
        if bool(with_metric) != self.has_metric:
            return None
        key = order_key(schema, sort, DESCENDING.get(order), lambda m: self.has_metric,
                        base.position)[0]
        ordered = moved(self.sorted, left, joined, key)
        in_storage = None
        if not with_metric:
            in_storage = moved(self.filtered, left, joined, _by_position(base.position))
        if ordered is None or (in_storage is None and not with_metric):
            return None
        return _Static(base.token, ordered, in_storage, with_metric)

    def merged(self, base, live, schema, sort, order):
        """This order with the filtered changed rows *live* placed into it."""
        present = lambda m: self.has_metric or any(m in r["metrics"] for r in live)  # noqa: E731
        key, ranked = order_key(schema, sort, DESCENDING.get(order), present, base.position)
        # Ranked by a metric no static row has: they all sort last, in storage order.
        static = self.filtered if ranked and not self.has_metric else self.sorted
        return MergedRows(static, sorted(live, key=key), key)


def _schema_key(schema):
    return json.dumps(schema or {}, sort_keys=True, default=str)


class LeaderboardCache(SetAnswers):
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
        self._importance = LRU(IMPORTANCE_RESULTS)
        self._groups = GroupCache(self, size)
        self.jobs = JobRollupCache(self, size)
        self._search = SearchIndexes()
        self._job_view = JobsView(self, size)
        self._subtree = SubtreeMatch(self, size)
        self._filtered_facets = LRU(size)
        self._top_counts = TopCounts(self)

    schema_key = staticmethod(_schema_key)

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

    def _ordered(self, snapshot, schema, last, f):
        """The rows passing the :class:`Filters` *f* in order (no ``job:*`` sort)."""
        base, bucket = self._base(snapshot)
        check_scope(base, f.scope)
        schema_key = _schema_key(schema)
        if last:
            return self._sorted.get(
                (base.token, bucket, schema_key, last) + f,
                lambda: sort_rows(base.tail(bucket, int(last), f), schema,
                                  sort=f.sort, last=last, order=f.order),
            )
        static = self.static_order(base, schema, f)
        if not base.patch.changed:
            return static.sorted
        return self._sorted.get(
            (base.token, bucket, schema_key, None) + f,
            lambda: static.merged(
                base, filtered(base.snapshot, base.changed_at(bucket), f), schema, f.sort, f.order,
            ),
        )

    def static_order(self, base, schema, filters):
        """*base*'s :class:`_Static` order for the :class:`Filters` *filters*."""
        schema_key = _schema_key(schema)
        return self._static.get(
            (base.token, schema_key) + filters,
            lambda: self._static_of(base, schema_key, schema, filters),
        )

    def _static_of(self, base, schema_key, schema, filters):
        """Moved on from the last generation this order was served in, across
        the deltas since (the dashboard asks for many orders, each only now
        and then); built when that is too far back or too much changed."""
        key = (schema_key,) + filters
        last = self._latest.peek(key)
        moves = last and self._deltas.since(last.token, base)
        static = moves and last.advanced(base, *moves, schema, filters)
        static = static or _Static.build(base, schema, filters,
                                         slots=self._candidates(base.snapshot, filters.query))
        self._latest.put(key, static)
        return static

    def _candidates(self, snapshot, query):
        """The slots of *snapshot* the search index says may pass *query*'s
        ``~`` clauses, or None (no clause it answers: every slot)."""
        if not query or ("~" not in query and "contains" not in query.lower()):
            return None
        return search_prefilter.candidates(parse_query(query), self._search.get(snapshot))

    def search(self, snapshot, text, limit, archived=False):
        """``{"results"}``: ⌘K "go to run" over every run (plan 23 S8)."""
        index = self._search.get(snapshot)
        return {"results": results(snapshot, index.ranked(text, limit, archived))}

    def warm_search(self, snapshot):
        """Build or move *snapshot*'s search index now (the refresher, off
        the request path)."""
        self._search.get(snapshot)

    def search_etag(self, snapshot, **params):
        """:meth:`search`'s ETag: the snapshot's token and the time bucket
        (statuses age), without building the leaderboard's base."""
        token = self._base_tokens.per_snapshot(snapshot, lambda: next(self._tokens))
        raw = json.dumps([_NONCE, token, self._bucket(), sorted(params.items())], default=str)
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    def page(
        self, snapshot, schema, sort=None, last=None, offset=0, limit=None,
        status=None, query=None, order=None, archived=False, scope=None, top=False,
        match_subtree=False, cursor=None,
    ):
        """What ``leaderboard`` answers for the same arguments, from the memo.

        Without *limit* a plain list of at most ``max_page`` rows; with it
        ``{"rows", "total", "next_cursor"}``, the page starting after
        *cursor* when given (a :class:`~vmn_exp.ui.leaderboard_cursor.BadCursor`
        when it is from another sort or filter), else at *offset*. Archived rows are left out unless *archived*;
        *scope* keeps a run's subtree (without it), *top* the top-level runs,
        each then carrying ``job`` (plan 23 S2), and with *match_subtree*
        the query matches their subtrees (:mod:`~vmn_exp.ui.leaderboard_subtree_match`).
        Raises ``QueryError`` on a
        bad *query*, :class:`~vmn_exp.ui.leaderboard_scope.UnknownScope` on an
        unknown *scope*.
        """
        f = Filters(sort, status, query, order, archived, scope, top)
        if match_subtree and not top:
            raise ValueError("match_subtree needs top=1")
        subtree = bool(match_subtree and query and query.strip())
        pager = self.pager(snapshot, schema, last, f, cursor, match_subtree,
                           ordered=(last, f._replace(query=None)) if subtree else None)
        if subtree:
            return self._subtree.page(snapshot, schema, last, offset, limit, f, pager)
        rows = self._job_view.ordered(snapshot, schema, last, f)
        return self.paged(snapshot, schema, rows, offset, limit, top, pager)

    def pager(self, snapshot, schema, last, f, cursor, match_subtree=False, ordered=None):
        """A :class:`~vmn_exp.ui.leaderboard_cursor.Pager` for the request
        (*last*, *f*, *match_subtree*) over the order of *ordered* (``(last,
        filters)``, default the request's), or a subsequence of it."""
        by_last, by = ordered or (last, f)
        return Pager(lambda projs: keyed(self, snapshot, schema, by_last, by, projs),
                     fingerprint(f, last, match_subtree), cursor)

    def paged(self, snapshot, schema, rows, offset, limit, top, pager):
        """*rows* cut as :meth:`page` answers (carrying ``job`` when *top*)."""
        offset = offset or 0
        if limit is None:
            cut = rows[offset : offset + self.max_page]
            return self._job_view.with_jobs(snapshot, schema, cut) if top else cut
        cut, after = pager.cut(rows, offset, limit)
        if top:
            cut = self._job_view.with_jobs(snapshot, schema, cut)
        return {"rows": cut, "total": len(rows), "next_cursor": after}

    def ordered(self, snapshot, schema, sort=None, status=None, order=None, archived=False,
                scope=None, top=False, query=None):
        """Every row passing the filters in :meth:`page`'s order, unpaged."""
        f = Filters(sort, status, query, order, archived, scope, top)
        return self._job_view.ordered(snapshot, schema, None, f)

    def groups(self, snapshot, schema, group, **params):
        """The grouped board (plan 22 K1), see
        :meth:`~vmn_exp.ui.leaderboard_group_cache.GroupCache.groups`."""
        return self._groups.groups(snapshot, schema, group, **params)

    def job_rollup(self, snapshot, schema, verstr):
        """*verstr*'s rollup over its whole subtree (plan 23 S1), or None when
        it is not a job; see :mod:`~vmn_exp.ui.job_rollup`. Archived runs
        are left out."""
        return self.jobs.job_rollup(snapshot, schema, verstr)

    def job_rollups(self, snapshot, schema):
        """``{verstr: compact rollup}`` for every job (for a Jobs view)."""
        return self.jobs.job_rollups(snapshot, schema)

    def rows(self, snapshot, archived=False):
        """Every row, with its status as of now, in storage order: no sort, for
        counting (archived rows only when *archived*)."""
        base, bucket = self._base(snapshot)
        return base.tail(bucket, 0, Filters(archived=archived))

    def columns(
        self, snapshot, schema, keys, limit=None, sort=None, status=None,
        query=None, order=None, archived=False, scope=None, top=False,
    ):
        """``{verstrs, idx, columns, total}`` over the first *limit* ordered rows.

        Raises ``ValueError`` on an unknown key, ``QueryError`` on a bad *query*.
        """
        limit = clamp_columns_limit(limit)
        keys = tuple(keys)
        base, bucket = self._base(snapshot)
        f = Filters(sort, status, query, order, archived, scope, top)
        return self._columns.get(
            (base.token, bucket, _schema_key(schema), keys, limit) + f,
            lambda: self._columns_payload(snapshot, schema, f, keys, limit),
        )

    def _columns_payload(self, snapshot, schema, f, keys, limit):
        rows = self._job_view.ordered(snapshot, schema, None, f)
        return columns_payload(rows[:limit], keys, len(rows))

    def etag(self, snapshot, schema, **params):
        """Changes whenever :meth:`page` could answer differently."""
        base, bucket = self._base(snapshot)
        raw = json.dumps(
            [_NONCE, base.token, bucket, _schema_key(schema), sorted(params.items())],
            default=str,
        )
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()
