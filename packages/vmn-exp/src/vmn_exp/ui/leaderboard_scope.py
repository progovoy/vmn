#!/usr/bin/env python3
"""The board's row filters (plan 23 S2): archived, ``top`` (top-level runs
only, the Jobs view: ``True`` all of them, ``"jobs"`` those with children,
``"singles"`` those without, plan 23 S7), ``scope`` (a run's subtree without the run), the
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

from vmn_exp.core.query_extra import reads_off_row
from vmn_exp.core.tree import OUTER, ancestors, subtree_verstrs
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.readers.experiments import apply_filters

JOBS, SINGLES = "jobs", "singles"
_TOPS = {None: False, "": False, "0": False, "false": False, "1": True, "true": True,
         JOBS: JOBS, SINGLES: SINGLES}


def top_filter(text):
    """The ``top`` filter a route's ``top=`` text names; ValueError when none."""
    key = text.lower() if isinstance(text, str) else text
    if key not in _TOPS:
        raise ValueError(f"top must be one of 1, {JOBS}, {SINGLES}, not {text!r}")
    return _TOPS[key]


def is_top(row, top):
    """Whether *row* is a top-level run of the kind *top* (truthy) keeps."""
    if row["depth"]:
        return False
    return top is True or (row["kind"] == OUTER) == (top == JOBS)


class UnknownScope(LookupError):
    """A ``scope`` naming no run of the snapshot."""


Filters = namedtuple("Filters", "sort status query order archived scope top",
                     defaults=(None, None, None, None, False, None, False))


def filtered(snapshot, rows, f):
    """*rows* of *snapshot* passing the filters *f* (``sort``/``order`` unused)."""
    rows = visible(rows, f.archived)
    if f.top:
        rows = [row for row in rows if is_top(row, f.top)]
    if f.scope is not None:
        edges = snapshot.edges
        rows = [row for row in rows if f.scope in ancestors(row["verstr"], edges)]
    return apply_filters(rows, f.status, f.query, snapshot)


def _rejudgeable(f):
    query = f.query
    return f.scope is None and not (query and query.strip() and reads_off_row(query))


def left_filtered(order, left, f):
    """Those of the *left* rows (of an older snapshot) *order* holds: judged
    again by their own fields when that is possible, else by identity."""
    if _rejudgeable(f):
        return filtered(None, left, f)
    ids = {id(row) for row in left}
    return [row for row in order if id(row) in ids]


def check_scope(base, scope):
    """Known: a run of *base*, or a parent its runs name (a loading index can
    hold an outer run's inner runs before the outer run itself)."""
    if scope is not None and scope not in base.position and not base.children_of.get(scope):
        raise UnknownScope(f"no run {scope!r}")


def scope_positions(base, scope):
    """Storage indexes of *scope*'s subtree without it, in storage order."""
    found = base.scopes.get(scope)
    if found is None:
        position = base.position
        found = base.scopes[scope] = sorted(
            position[v] for v in subtree_verstrs(scope, base.children_of)[1:] if v in position)
    return found
