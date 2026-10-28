#!/usr/bin/env python3
"""Board orders and groupings that read ``up`` fields (plan 28 N1), moved
across index generations.

A moved order re-judges only the rows that changed. A run's ``up`` field
reads its ancestors, so it can answer anew while the run itself stays the
same object: when an ancestor's params, tags or name change. Like a re-link
re-making every row below it (:mod:`~vmn_exp.ui.leaderboard_tree`), such a
change makes the order whole again: :func:`stamped` notes what an order's
``up`` fields read of its snapshot (:func:`~vmn_exp.core.query_up.parent_rows`,
once per snapshot) and :func:`movable` refuses to move it past a generation
where that differs, so it is built afresh. Other changes move it as before.
"""
from vmn_exp.core.query import query_roots
from vmn_exp.core.query_up import UP, ancestors_moved, parent_rows


def query_reads_up(query):
    """Whether *query* reads an ``up`` field."""
    return bool(query and query.strip()) and UP in query_roots(query)


def stamped(order, snapshot, reads_up):
    """*order* (a static order or grouping of *snapshot*) noting what its
    ``up`` fields read, when *reads_up*."""
    order.parents = parent_rows(snapshot) if reads_up else None
    return order


def movable(last, snapshot):
    """Whether the order *last* may move on to *snapshot*: no ancestor its
    ``up`` fields read reads otherwise there."""
    return last.parents is None or not ancestors_moved(last.parents, snapshot)
