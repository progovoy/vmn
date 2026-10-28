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
from collections import namedtuple

import vmn_exp.core.status as experiment_status
from vmn_exp.core.gc_pause import freeze_long_lived, gc_paused
from vmn_exp.core.log import primary_metric
from vmn_exp.core.query import parse_query
from vmn_exp.core.status import status_fields, with_queue_sec
from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui import search_prefilter
from vmn_exp.ui.attention import AttentionCounts
from vmn_exp.ui.failure_signature import signed
from vmn_exp.ui.http_params import MAX_PAGE
from vmn_exp.ui.job_rollup_cache import JobRollupCache
from vmn_exp.ui.leaderboard_answers import IMPORTANCE_RESULTS, SetAnswers
from vmn_exp.ui.leaderboard_columns import clamp_columns_limit, columns_payload
from vmn_exp.ui.leaderboard_children import TreeNodes
from vmn_exp.ui.leaderboard_cursor import Pager, fingerprint, keyed
from vmn_exp.ui.leaderboard_delta import (
    DeltaLog,
    moved,
    row_delta,
    same_index,
    static_moves,
)
from vmn_exp.ui.leaderboard_facets import Facets
from vmn_exp.ui.leaderboard_group_cache import GroupCache
from vmn_exp.ui.leaderboard_jobs import JobsView
from vmn_exp.ui.leaderboard_live import LivePatch, MergedRows, is_live, order_key
from vmn_exp.ui.leaderboard_scope import (
    Filters,
    check_filters,
    filtered,
    left_filtered,
    narrowed_slots,
)
from vmn_exp.ui.leaderboard_subtree_match import SubtreeMatch
from vmn_exp.ui.leaderboard_successor import current, latest, live_outers
from vmn_exp.ui.leaderboard_top_counts import TopCounts
from vmn_exp.ui.leaderboard_tree import derive_tree, tree_index
from vmn_exp.ui.leaderboard_up import ancestors_changed, query_reads_up
from vmn_exp.ui.leaderboard_warm import BoardWarmer
from vmn_exp.ui.memo import LRU, Generations, GroupedLRU
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING
from vmn_exp.ui.readers.experiments import sort_rows, split_by_of
from vmn_exp.ui.search_index import SearchIndexes
from vmn_exp.ui.search_rank import results
from vmn_exp.ui.sibling_durations import SiblingDurations, restamped, stamped
from vmn_exp.ui.status_counts import StatusCounts

BUCKET_SEC = 2
# Orders moved on across generations: the dashboard's mix of sorts and
# queries at 100k rows, each a list of row references.
LATEST_ORDERS = 64
# Index generations each app keeps in the per-generation caches: the newest
# serves, the one before it covers a refresh's old/new snapshot handoff.
GENERATIONS_KEPT = 3
# Seconds a request waits on another thread's build of a generation's base
# before it answers from the app's previous generation instead.
BASE_WAIT_SEC = 2.0
# Apps whose bases are kept (two each), least recently used leaving first.
BASE_APPS = 8
# Tokens are per process, so an ETag from before a restart never matches.
_NONCE = os.urandom(8).hex()


def _status(snapshot, row):
    """*row*'s status fields, judged with the store's write time too."""
    verstr = row["verstr"]
    return with_queue_sec(row, status_fields(
        snapshot.run_states.get(verstr),
        observed_at=snapshot.run_state_observed_at.get(verstr),
    ))


def _restated(snapshot, row):
    """A copy of *row* with its status fields as of now."""
    return signed({**row, **_status(snapshot, row)})


class _Base:
    """One snapshot's rows with their status and tree fields."""

    def __init__(self, snapshot, token, bucket, rows, position, patch, tree, siblings):
        self.snapshot = snapshot
        self.siblings = siblings  # the duration_ratio medians (sibling_durations)
        self.token = token
        self.rows = rows
        self.position = position
        self.patch = patch
        self.children_of, self.child_statuses = tree
        self.scopes = {}  # {scope: storage indexes of its subtree}
        # (previous base's token, static rows that left, static rows that joined)
        self.delta = None
        self.up_moved = False  # whether the delta changed what an up field reads
        self._at = (bucket, [rows[i] for i in patch.changed])
        self._patched = (None, None)  # (changed_at's rows, patched() of them)
        self._lock = TracedLock(f"leaderboard base:{getattr(snapshot, 'app_name', None)}")
        # The base that follows once a live outer run went stuck (leaderboard_successor).
        self.live_outers = live_outers(patch, rows)
        self.successor = self.outers_checked = None
        self.successor_lock = TracedLock(
            f"leaderboard successor:{getattr(snapshot, 'app_name', None)}")
        self.built_bucket = bucket

    @classmethod
    def build(cls, snapshot, token, bucket, split=None):
        """From scratch: O(N) — a copy of every row, so with collection
        paused (see :mod:`~vmn_exp.core.gc_pause`). *split*: the field
        ``duration_ratio`` compares siblings by (none: the parent alone)."""
        states = snapshot.run_states
        with gc_paused():
            live = [i for i, row in enumerate(snapshot.rows) if is_live(snapshot, row["verstr"])]
            rows = [signed(row) for row in
                    annotate_rows(snapshot.rows, states, snapshot.run_state_observed_at)]
            siblings = SiblingDurations.stamping(rows, split)
            position = {row["verstr"]: i for i, row in enumerate(rows)}
            patch = LivePatch.of_rows(rows, live, position)
            return cls(snapshot, token, bucket, rows, position, patch, tree_index(rows), siblings)

    @classmethod
    def derived(cls, prev, snapshot, token, bucket, delta=None):
        """From *prev*'s base, re-deriving only what changed (*delta*:
        ``(storage indexes, verstrs gone)``, else found), its ratios against
        siblings by *prev*'s split; None when the delta is large, a verstr
        repeats or a parent chain loops."""
        delta = delta or row_delta(prev, snapshot)
        if delta is None:
            return None
        fresh_at, gone = delta
        # The same snapshot keeps every slot: its positions are shared.
        position = prev.position if snapshot is prev.snapshot else dict(prev.position)
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
        was = [prev.rows[prev.position[v]] for v in (*fresh, *gone) if v in prev.position]
        siblings, regrouped = prev.siblings.advanced(was, fresh.values())
        copied = restamped(rows, position, children_of, siblings, regrouped, fresh, rebuilt)
        live = sorted(position[v] for v in fresh if is_live(snapshot, v))
        patch = LivePatch.from_counts(rows, live, position, snapshot.edges, counts)
        base = cls(snapshot, token, bucket, rows, position, patch, (children_of, counts),
                   siblings)
        base.delta = (prev.token,) + static_moves(prev, base, rebuilt | gone | copied, copied)
        base.up_moved = ancestors_changed(prev, fresh, gone, children_of)
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
        at = narrowed_slots(self, f)
        at = range(len(self.rows)) if at is None else at
        out, stop, chunk = [], len(at), max(count, 64)
        while stop and (count < 1 or len(out) < count):
            start = max(0, stop - chunk)
            window = [patched.get(i, self.rows[i]) for i in at[start:stop]]
            out = filtered(self.snapshot, window, f) + out
            stop, chunk = start, chunk * 2
        return out

    def _rederive_live(self):
        fresh = {i: _restated(self.snapshot, self.rows[i]) for i in self.patch.live}
        stamped(fresh.values(), self.siblings)
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
        at = narrowed_slots(base, f)
        if slots is not None:
            at = sorted(slots) if at is None else sorted(set(at) & slots)
        elif at is None:
            at = range(len(base.rows))
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


# One family of orders: by (base, schema, filters); (schema, filters) ->
# the newest _Static; merged with the live rows.
_Orders = namedtuple("_Orders", "static latest merged")


def _schema_key(schema):
    return json.dumps(schema or {}, sort_keys=True, default=str)


def _no_conf(snapshot):
    return {}, {}


class LeaderboardCache(SetAnswers):
    def __init__(self, max_page=MAX_PAGE, bucket_sec=BUCKET_SEC, size=32,
                 base_wait_sec=BASE_WAIT_SEC, conf_of=_no_conf):
        """*conf_of(snapshot)* -> ``(metrics schema, experiment.ui)`` of the
        app whose index published *snapshot* (its conf over its store
        settings): what the board warm-up sorts by, job rollups read
        their progress names from and ``duration_ratio`` its split by."""
        self.conf_of = conf_of
        self.max_page = max_page
        self.bucket_sec = bucket_sec
        self.base_wait_sec = base_wait_sec
        self._tokens = itertools.count(1)
        # A snapshot's token identifies it across every app/workspace sharing
        # this cache, so it must never repeat (hence the counter above, not
        # e.g. snapshot.generation, which restarts per app). Keeping it in
        # its own small LRU, separate from the heavy _bases below, means a
        # snapshot recomputed after its _Base was evicted still gets back the
        # token it had before, so its etag stays stable; entries here are a
        # few bytes each, so a larger bound than _bases costs nothing.
        self._base_tokens = LRU(size, name="leaderboard base tokens")
        # Each generation's _Base is a full copy of annotated rows (heavy at
        # 100k+ runs); keep just enough per app to survive a refresh's
        # old/new snapshot handoff, and to derive the next generation from —
        # per app, so going round apps (or a /metrics scrape) rebuilds none.
        self._bases = GroupedLRU(2, BASE_APPS, lambda hit: hit[1].snapshot.app_name,
                                 name="leaderboard bases")
        # Caches keyed by a base token first keep each app's newest generations.
        self.generations = Generations(GENERATIONS_KEPT)
        track = self.generations.track
        self._facets = Facets()
        # The board's orders, and the tree's children orders (plan 28 N6) in
        # LRUs of their own, so expanding nodes never evicts the board's.
        self._orders = {tree: _Orders(track(LRU(size)), LRU(LATEST_ORDERS), track(LRU(size)))
                        for tree in (False, True)}
        self._deltas = DeltaLog()
        self._columns = track(LRU(size))
        self._importance = LRU(IMPORTANCE_RESULTS)
        self._groups = GroupCache(self, size)
        self.jobs = JobRollupCache(self, size)
        self._search = SearchIndexes()
        self._job_view = JobsView(self, size)
        self._subtree = SubtreeMatch(self, size)
        self._filtered_facets = track(LRU(size))
        self._top_counts = TopCounts(self)
        self._status_counts = StatusCounts(self)
        self.attention = AttentionCounts(self)
        self.tree_nodes = TreeNodes(self, size)
        self._warmer = BoardWarmer(self)

    schema_key = staticmethod(_schema_key)

    def _bucket(self):
        return int(experiment_status._now().timestamp() // self.bucket_sec)

    def _base(self, snapshot):
        """``(base, bucket)``; the bucket is None while nothing is live.

        Waiting on another thread's build of *snapshot*'s base for over
        ``base_wait_sec``, the previous generation of its index answers
        instead (when one is kept)."""
        bucket = self._bucket()
        # Siblings (duration_ratio) share a parent and a value of the app's split.
        split = split_by_of(self.conf_of(snapshot)[1] or {})
        token = self._base_tokens.per_snapshot(snapshot, lambda: next(self._tokens), key=(split,))
        base = self._bases.per_snapshot(
            snapshot, lambda: self._new_base(snapshot, token, bucket, split), key=(split,),
            stale=lambda: self._previous_base(snapshot),
            wait_sec=self.base_wait_sec,
        )
        base = current(base, bucket, self._follow)
        return base, (bucket if base.patch.live else None)

    def _latest_base(self, app_name, accept=lambda base: True):
        kept = [base for _, base in self._bases.values()
                if base.snapshot.app_name == app_name and accept(base)]
        return max(kept, key=lambda base: base.token, default=None)

    def _previous_base(self, snapshot):
        """The newest kept base of *snapshot*'s own index, else None."""
        return self._latest_base(snapshot.app_name,
                                 lambda base: same_index(base.snapshot, snapshot))

    def _follow(self, prev):
        """*prev*'s successor for its own snapshot (a live outer run went
        stuck): derived like a new generation, else built."""
        token, bucket = next(self._tokens), self._bucket()
        live = (sorted(prev.patch.live), set())  # nothing else changed
        base = _Base.derived(prev, prev.snapshot, token, bucket, delta=live)
        if base:
            self._deltas.add(base)
        base = base or _Base.build(prev.snapshot, token, bucket, prev.siblings.split)
        self.generations.advance(prev.snapshot.app_name, token)
        return base

    def _new_base(self, snapshot, token, bucket, split=None):
        """Derived from the app's latest kept base, else built. Any base is a
        valid start (even another workspace's): the delta is found by identity."""
        prev = self._latest_base(snapshot.app_name)
        prev = prev and latest(prev, bucket)
        same_split = prev and prev.siblings.split == split
        base = same_split and _Base.derived(prev, snapshot, token, bucket)
        if base:
            self._deltas.add(base)
        else:
            base = _Base.build(snapshot, token, bucket, split)
            # A whole board's new rows; a derived base's few are not worth a
            # freeze, which keeps every cycle alive now for good.
            freeze_long_lived()
        self.generations.advance(snapshot.app_name, token)
        return base

    def _ordered(self, snapshot, schema, last, f):
        """The rows passing the :class:`Filters` *f* in order (no ``job:*`` sort)."""
        base, bucket = self._base(snapshot)
        check_filters(base, f)
        schema_key = _schema_key(schema)
        merged = self._orders_for(f).merged
        if last:
            return merged.get(
                (base.token, bucket, schema_key, last) + f,
                lambda: sort_rows(base.tail(bucket, int(last), f), schema,
                                  sort=f.sort, last=last, order=f.order),
            )
        static = self.static_order(base, schema, f)
        if not base.patch.changed:
            return static.sorted
        return merged.get(
            (base.token, bucket, schema_key, None) + f,
            lambda: static.merged(
                base, filtered(base.snapshot, base.changed_at(bucket), f), schema, f.sort, f.order,
            ),
        )

    def _orders_for(self, f):
        return self._orders[f.children_of is not None]

    def static_order(self, base, schema, filters):
        """*base*'s :class:`_Static` order for the :class:`Filters` *filters*."""
        schema_key = _schema_key(schema)
        return self._orders_for(filters).static.get(
            (base.token, schema_key) + filters,
            lambda: self._static_of(base, schema_key, schema, filters),
        )

    def _static_of(self, base, schema_key, schema, filters):
        """Moved on from the last generation this order was served in, across
        the deltas since (the dashboard asks for many orders, each only now
        and then); built when that is too far back or too much changed."""
        key = (schema_key,) + filters
        latest = self._orders_for(filters).latest
        last = latest.peek(key)
        reads_up = query_reads_up(filters.query) or query_reads_up(filters.top_query)
        moves = last and self._deltas.since(last.token, base, reads_up)
        static = moves and last.advanced(base, *moves, schema, filters)
        static = static or _Static.build(base, schema, filters,
                                         slots=self._candidates(base.snapshot, filters.query,
                                                                base.position))
        latest.put(key, static)
        return static

    def _candidates(self, snapshot, query, position=None):
        """The slots of *snapshot* the search index says may pass *query*'s
        ``~`` clauses (and, given its storage *position*, its ``verstr in``
        clauses), or None (no clause it answers: every slot)."""
        if not query or ("~" not in query and "contains" not in query.lower()
                         and (position is None or "verstr" not in query)):
            return None
        slots = search_prefilter.Slots(lambda: self._search.get(snapshot), position)
        return search_prefilter.candidates(parse_query(query), slots)

    def search(self, snapshot, text, limit, archived=False):
        """``{"results"}``: ⌘K "go to run" over every run (plan 23 S8)."""
        index = self._search.get(snapshot)
        return {"results": results(snapshot, index.ranked(text, limit, archived))}

    def warm(self, snapshot):
        """Build or move *snapshot*'s board base, search index, facets and
        default first pages now (the refresher and the startup warm-up, off
        the request path; see :mod:`~vmn_exp.ui.leaderboard_warm`)."""
        self._warmer.warm(snapshot)

    def warm_search(self, snapshot):
        """Build or move *snapshot*'s search index now."""
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
        match_subtree=False, cursor=None, attention=(), children_of=None, split=None,
        top_query=None,
    ):
        """What ``leaderboard`` answers for the same arguments, from the memo.

        Without *limit* a plain list of at most ``max_page`` rows; with it
        ``{"rows", "total", "next_cursor"}``, the page starting after
        *cursor* when given (a :class:`~vmn_exp.ui.leaderboard_cursor.BadCursor`
        when it is from another sort or filter), else at *offset*. Archived rows are left out unless *archived*;
        *scope* keeps a run's subtree (without it), *top* the top-level runs,
        each then carrying ``job`` (plan 23 S2), and with *match_subtree*
        the query matches their subtrees (:mod:`~vmn_exp.ui.leaderboard_subtree_match`);
        their ``job`` carries the *attention* queries' counts (:mod:`~vmn_exp.ui.attention`).
        *children_of* keeps a run's direct children, always paged, as the
        tree serves them (split by the *split* field, plan 28 N6,
        :mod:`~vmn_exp.ui.leaderboard_children`). *top_query* keeps the top
        rows passing it by their own fields (plan 28 §4.5; needs *top*).
        Raises ``QueryError`` on a
        bad *query*, :class:`~vmn_exp.ui.leaderboard_scope.UnknownScope` on an
        unknown *scope*.
        """
        f = Filters(sort, status, query, order, archived, scope, top, children_of, top_query)
        if match_subtree and not top:
            raise ValueError("match_subtree needs top=1")
        if top_query and not top:
            raise ValueError("top_q needs top=1")
        if top and children_of is not None:
            raise ValueError("children_of cannot be combined with top")
        subtree = bool(match_subtree and query and query.strip())
        pager = self.pager(snapshot, schema, last, f, cursor, match_subtree,
                           ordered=(last, f._replace(query=None)) if subtree else None,
                           attention=attention)
        if subtree:
            return self._subtree.page(snapshot, schema, last, offset, limit, f, pager, attention)
        rows = self._job_view.ordered(snapshot, schema, last, f, attention)
        if children_of is not None:
            cut, after = pager.cut(rows, offset or 0, self.max_page if limit is None else limit)
            cut = self.tree_nodes.rows(snapshot, schema, cut, children_of, attention, split)
            return {"rows": cut, "total": len(rows), "next_cursor": after}
        return self.paged(snapshot, schema, rows, offset, limit, top, pager, attention)

    def pager(self, snapshot, schema, last, f, cursor, match_subtree=False, ordered=None,
              attention=()):
        """A :class:`~vmn_exp.ui.leaderboard_cursor.Pager` for the request
        (*last*, *f*, *match_subtree*) over the order of *ordered* (``(last,
        filters)``, default the request's), or a subsequence of it."""
        by_last, by = ordered or (last, f)
        return Pager(lambda projs: keyed(self, snapshot, schema, by_last, by, projs, attention),
                     fingerprint(f, last, match_subtree), cursor)

    def paged(self, snapshot, schema, rows, offset, limit, top, pager, attention=()):
        """*rows* cut as :meth:`page` answers (carrying ``job`` when *top*)."""
        offset = offset or 0
        if limit is None:
            cut = rows[offset : offset + self.max_page]
            return self._job_view.with_jobs(snapshot, schema, cut, attention) if top else cut
        cut, after = pager.cut(rows, offset, limit)
        if top:
            cut = self._job_view.with_jobs(snapshot, schema, cut, attention)
        return {"rows": cut, "total": len(rows), "next_cursor": after}

    def ordered(self, snapshot, schema, sort=None, status=None, order=None, archived=False,
                scope=None, top=False, query=None, top_query=None):
        """Every row passing the filters in :meth:`page`'s order, unpaged."""
        f = Filters(sort, status, query, order, archived, scope, top, top_query=top_query)
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
        return columns_payload(rows[:limit], keys, len(rows), snapshot.system_metrics_of,
                               snapshot)

    def etag(self, snapshot, schema, **params):
        """Changes whenever :meth:`page` could answer differently."""
        base, bucket = self._base(snapshot)
        raw = json.dumps(
            [_NONCE, base.token, bucket, _schema_key(schema), self.jobs.progress_names(snapshot),
             sorted(params.items())],
            default=str,
        )
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()
