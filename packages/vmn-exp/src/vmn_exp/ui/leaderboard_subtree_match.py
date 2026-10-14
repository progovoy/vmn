#!/usr/bin/env python3
"""The Jobs view's search over every run (plan 23 S8b, ``match_subtree``).

A top-level row is kept when it, or any run of its subtree, passes the
query: the passing runs of the whole app are found once per base and time
bucket (the search index narrows ``~`` clauses to its candidates, see
:mod:`~vmn_exp.ui.search_prefilter`) and counted per top-level ancestor
(the rows' ``root``). The kept rows are the Jobs view's order without the
query (the status filter still reads their own fields), each carrying
``matched``, its tree's count; a page also carries ``jobs_matched`` and
``runs_matched`` (every passing run of the app).
"""
from collections import Counter

from vmn_exp.ui.leaderboard_scope import Filters, filtered
from vmn_exp.ui.memo import LRU


class SubtreeMatch:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._hits = LRU(size)

    def hits(self, snapshot, query, archived):
        """``Counter({top-level verstr: runs of its tree passing *query*})``."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        return self._hits.get(
            (base.token, bucket, query, archived),
            lambda: _hits(base, bucket, cache._candidates(snapshot, query), query, archived))

    def page(self, snapshot, schema, last, offset, limit, f):
        """:meth:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache.page` for
        the :class:`Filters` *f* (``top`` set), matching subtrees."""
        cache = self._cache
        hits = self.hits(snapshot, f.query, f.archived)
        rows = cache._job_view.ordered(snapshot, schema, last, f._replace(query=None))
        kept = [row for row in rows if row["verstr"] in hits]
        out = cache.paged(snapshot, schema, kept, offset, limit, f.top)
        for row in out if limit is None else out["rows"]:
            row["matched"] = hits[row["verstr"]]  # with_jobs' copies
        if limit is None:
            return out
        return dict(out, jobs_matched=len(kept), runs_matched=sum(hits.values()))


def _hits(base, bucket, slots, query, archived):
    patched = dict(zip(base.patch.changed, base.changed_at(bucket)))
    at = range(len(base.rows)) if slots is None else sorted(slots)
    rows = [patched.get(i, base.rows[i]) for i in at]
    passing = filtered(base.snapshot, rows, Filters(query=query, archived=archived))
    return Counter(row["root"] or row["verstr"] for row in passing)
