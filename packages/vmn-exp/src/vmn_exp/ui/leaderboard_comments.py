"""Per-run comment counts on leaderboard rows (plan 13 §8.2).

Counts come from the workspace's report index, not the experiment index
snapshot, so they are joined into a page's rows after the memoized pipeline
(copies: cached rows are shared). A query reading ``comments`` cannot use the
memoized filtered orders — the counts change without a new snapshot — so it
filters the memoized unfiltered order instead.
"""
from vmn_exp.core.query import filter_rows, query_roots


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


def page_by_comments(cache, snapshot, schema, counts, sort=None, last=None, offset=0,
                     limit=None, status=None, query=None, order=None, archived=False):
    """:meth:`LeaderboardCache.page` for a *query* reading ``comments``."""
    ordered = cache.ordered(snapshot, schema, sort, status, order, archived)
    extra = {"comments": counts.get, "outputs": snapshot.outputs_of}
    rows = filter_rows(ordered, query, extra=extra)
    if last:
        newest = set(sorted(row["idx"] for row in rows)[-int(last):])
        rows = [row for row in rows if row["idx"] in newest]
    offset = offset or 0
    if limit is None:
        return rows[offset : offset + cache.max_page]
    return {"rows": rows[offset : offset + limit], "total": len(rows)}
