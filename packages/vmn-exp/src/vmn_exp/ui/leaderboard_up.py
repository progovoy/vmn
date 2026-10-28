#!/usr/bin/env python3
"""Board orders and groupings that read ``up`` fields (plan 28 N1), moved
across index generations.

A moved order re-judges only the rows that changed. A run's ``up`` field
reads its ancestors, so it can answer anew while the run itself stays the
same object: when an ancestor's params, tags or name change. Like a re-link
re-making every row below it (:mod:`~vmn_exp.ui.leaderboard_tree`), such a
change makes the order whole again: a generation whose changed rows include
one (:func:`ancestors_changed`, O(changed rows)) is marked on its delta, and
:meth:`~vmn_exp.ui.leaderboard_delta.DeltaLog.since` moves no order that
:func:`query_reads_up` (or groups by an ``up`` field) across it.
"""
from vmn_exp.core.query import query_roots
from vmn_exp.core.query_up import UP, up_view


def query_reads_up(query):
    """Whether *query* reads an ``up`` field."""
    return bool(query and query.strip()) and UP in query_roots(query)


def ancestors_changed(prev, fresh, gone, children_of):
    """Whether a run with children (in *prev*'s base or *children_of*, the
    new tree) reads otherwise to an ``up`` field: it changed (*fresh*
    ``{verstr: new row}``), appeared or left (*gone*)."""
    for verstr in (*fresh, *gone):
        if not (children_of.get(verstr) or prev.children_of.get(verstr)):
            continue
        at = prev.position.get(verstr)
        old = prev.rows[at] if at is not None else None
        if up_view(old) != up_view(fresh.get(verstr)):
            return True
    return False
