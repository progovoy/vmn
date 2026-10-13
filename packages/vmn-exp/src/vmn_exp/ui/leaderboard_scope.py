#!/usr/bin/env python3
"""The board's row filters (plan 23 S2): archived, ``top`` (top-level runs
only, the Jobs view), ``scope`` (a run's subtree without the run), the
status whitelist and the query language, as one hashable :class:`Filters`
the cached orders are keyed by.

A row is in a scope when the scope is on its parent chain (the snapshot's
``edges``); a scoped order is built from the scope's subtree alone
(:func:`scope_positions`), so a 5000-run job costs 5000 rows, not the app.
Re-linking a run makes every row below it a new object
(:mod:`~vmn_exp.ui.leaderboard_tree`), so moved orders see them leave and
join. A row that left is judged by whether the order holds it (identity)
when its membership cannot be judged again: a scope, or a query reading the
snapshot's ``outputs`` or ancestry (``under()``).
"""
from collections import namedtuple

from vmn_exp.core.query import query_roots
from vmn_exp.core.tree import ancestors, subtree_verstrs
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.readers.experiments import SNAPSHOT_FIELDS, apply_filters


class UnknownScope(LookupError):
    """A ``scope`` naming no run of the snapshot."""


Filters = namedtuple("Filters", "sort status query order archived scope top",
                     defaults=(None, None, None, None, False, None, False))


def filtered(snapshot, rows, f):
    """*rows* of *snapshot* passing the filters *f* (``sort``/``order`` unused)."""
    rows = visible(rows, f.archived)
    if f.top:
        rows = [row for row in rows if not row["depth"]]
    if f.scope is not None:
        edges = snapshot.edges
        rows = [row for row in rows if f.scope in ancestors(row["verstr"], edges)]
    return apply_filters(rows, f.status, f.query, snapshot)


def _rejudgeable(f):
    query = f.query
    reads = query_roots(query) if query and query.strip() else ()
    return f.scope is None and not SNAPSHOT_FIELDS.intersection(reads)


def left_filtered(order, left, f):
    """Those of the *left* rows (of an older snapshot) *order* holds: judged
    again by their own fields when that is possible, else by identity."""
    if _rejudgeable(f):
        return filtered(None, left, f)
    ids = {id(row) for row in left}
    return [row for row in order if id(row) in ids]


def check_scope(base, scope):
    if scope is not None and scope not in base.position:
        raise UnknownScope(f"no run {scope!r}")


def scope_positions(base, scope):
    """Storage indexes of *scope*'s subtree without it, in storage order."""
    found = base.scopes.get(scope)
    if found is None:
        position = base.position
        found = base.scopes[scope] = sorted(
            position[v] for v in subtree_verstrs(scope, base.children_of)[1:] if v in position)
    return found
