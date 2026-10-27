#!/usr/bin/env python3
"""A generation's ``settled`` fields (:mod:`~vmn_exp.core.settle`) derived
from the previous generation's, for :func:`~vmn_exp.ui.leaderboard_tree.derive_tree`.

A row's ``settled`` reads its own status and whether its parent closes its
children. Between two generations only the changed and re-linked rows can
answer differently — and the children of any row whose closing flips (an
outer run that ends or starts again, a never-started container under it),
recursively: O(that subtree) once, never O(all rows).
"""
import heapq

from vmn_exp.core.settle import closes, settled_as


def resettled(seeds, was, parent_of, children_of, was_closed):
    """Re-settle *seeds* and every row below one whose closing flips,
    parents before children (by *was.depth*), into *was.settled*.

    *was* gives a row as it stands (``row``), its ``settled_of`` (the new
    value once re-settled) and its new ``depth``; *parent_of(verstr)* its
    present parent or None; *was_closed(verstr)* whether it closed its
    children in the previous generation."""
    queue = [(was.depth(v), v) for v in seeds]
    heapq.heapify(queue)
    queued = set(seeds)

    def closes_now(verstr):
        return closes(was.row(verstr)["status"], was.settled_of(verstr))

    while queue:
        _, verstr = heapq.heappop(queue)
        parent = parent_of(verstr)
        was.settled[verstr] = settled_as(was.row(verstr)["status"],
                                         parent is not None and closes_now(parent))
        if closes_now(verstr) == was_closed(verstr):
            continue
        for kid in children_of.get(verstr, ()):
            if kid not in queued:
                queued.add(kid)
                heapq.heappush(queue, (was.depth(kid), kid))
