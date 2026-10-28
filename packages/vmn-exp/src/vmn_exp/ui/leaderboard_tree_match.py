#!/usr/bin/env python3
"""A tree page's filters over subtrees (plan 28 N6, ``children_of=<v>`` with
``match_subtree``): a child is kept when it, or any run below it, passes the
status filter and the query, so a filtered tree still leads from the outer
run down to the runs that match.

The passing runs of the tree a request reads (its top-level run's subtree)
are found once per base, time bucket and filter, and counted up their
ancestor chains. The kept children are the children's order without the
filters, each carrying ``matched`` (its subtree's passing runs, itself
included) and opening when a run below it passes.
"""
from collections import Counter

from vmn_exp.core.tree import ancestors
from vmn_exp.ui.leaderboard_children import tree_root
from vmn_exp.ui.leaderboard_scope import Filters, filtered, scope_positions
from vmn_exp.ui.memo import LRU


def filters_subtrees(f):
    """Whether the :class:`Filters` *f* holds a filter to match over subtrees."""
    return bool(f.status or (f.query and f.query.strip()))


class TreeMatch:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._hits = cache.generations.track(LRU(size))

    def hits(self, snapshot, f):
        """``(Counter({node: passing runs at or below it}), passing verstrs)``
        over the tree of *f*'s ``children_of``."""
        base, bucket = self._cache._base(snapshot)
        root = tree_root(base, f.children_of)
        return self._hits.get((base.token, bucket, f.query, f.status, f.archived, root),
                              lambda: _hits(base, bucket, root, f))

    def page(self, snapshot, schema, last, offset, limit, f, cursor, attention=(), split=None):
        """:meth:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache.page` of
        the children *f* names, kept by their subtrees."""
        cache = self._cache
        plain = f._replace(status=None, query=None)
        pager = cache.pager(snapshot, schema, last, f, cursor, True, ordered=(last, plain),
                            attention=attention)
        counts, passing = self.hits(snapshot, f)
        rows = cache._job_view.ordered(snapshot, schema, last, plain, attention)
        kept = [row for row in rows if counts[row["verstr"]]]
        limit = cache.max_page if limit is None else limit
        cut, after = pager.cut(kept, offset or 0, limit)
        cut = cache.tree_nodes.rows(snapshot, schema, cut, f.children_of, attention, split)
        for row in cut:
            n = row["matched"] = counts[row["verstr"]]
            row["open"] = row["open"] or n > (row["verstr"] in passing)
        return {"rows": cut, "total": len(kept), "next_cursor": after}


def _hits(base, bucket, root, f):
    patched = base.patched(bucket)
    at = scope_positions(base, root)
    if root in base.position:
        at = [base.position[root], *at]
    rows = [patched.get(i, base.rows[i]) for i in at]
    passing = filtered(base.snapshot, rows,
                       Filters(status=f.status, query=f.query, archived=f.archived))
    edges = base.snapshot.edges
    counts = Counter()
    for row in passing:
        counts.update((row["verstr"], *ancestors(row["verstr"], edges)))
    return counts, frozenset(row["verstr"] for row in passing)
