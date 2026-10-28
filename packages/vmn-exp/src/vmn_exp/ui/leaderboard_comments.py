"""Per-run comment counts on leaderboard rows (plan 13 §8.2).

Counts come from the workspace's report index, not the experiment index
snapshot, so they are joined into a page's rows after the memoized pipeline
(copies: cached rows are shared). A query reading ``comments`` cannot use the
memoized filtered orders — the counts change without a new snapshot — so it
filters the memoized unfiltered order instead.
"""
from vmn_exp.core.query import filter_rows, query_roots
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.ui.leaderboard_scope import Filters


def reads_comments(query):
    return bool(query and query.strip()) and "comments" in query_roots(query)


def joined(payload, counts):
    """*payload* (a row list or ``{rows, total}``) with ``comments`` on the
    rows *counts* has."""
    if not counts:
        return payload
    if isinstance(payload, dict):
        return dict(payload, rows=joined(payload["rows"], counts))
    return [dict(row, comments=counts[row["verstr"]]) if row["verstr"] in counts else row
            for row in payload]


def joined_groups(payload, counts):
    """A grouped answer (one group, or ``{groups, ...}``) with ``comments`` on its rows."""
    if not counts:
        return payload
    if "groups" in payload:
        return dict(payload, groups=[joined_groups(g, counts) for g in payload["groups"]])
    return dict(payload, rows=joined(payload["rows"], counts))


def groups_by_comments(cache, snapshot, schema, group, counts, query=None, **params):
    """:meth:`LeaderboardCache.groups` for a *query* reading ``comments``."""
    extra = {"comments": counts.get, **lean_extra(snapshot)}
    return cache.groups(snapshot, schema, group,
                        rows_filter=lambda rows: filter_rows(rows, query, extra=extra), **params)


def page_by_comments(cache, snapshot, schema, counts, sort=None, last=None, offset=0,
                     limit=None, status=None, query=None, order=None, archived=False,
                     scope=None, top=False, cursor=None, top_query=None):
    """:meth:`LeaderboardCache.page` for a *query* reading ``comments``."""
    f = Filters(sort, status, query, order, archived, scope, top, top_query=top_query)
    # The rows are the unfiltered order's (no query, no last) narrowed.
    pager = cache.pager(snapshot, schema, last, f, cursor, ordered=(None, f._replace(query=None)))
    ordered = cache.ordered(snapshot, schema, sort, status, order, archived, scope, top,
                            top_query=top_query)
    extra = {"comments": counts.get, **lean_extra(snapshot)}
    rows = filter_rows(ordered, query, extra=extra)
    if last:
        newest = set(sorted(row["idx"] for row in rows)[-int(last):])
        rows = [row for row in rows if row["idx"] in newest]
    return cache.paged(snapshot, schema, rows, offset, limit, top, pager)
