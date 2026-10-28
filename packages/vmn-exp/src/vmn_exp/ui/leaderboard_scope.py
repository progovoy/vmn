#!/usr/bin/env python3
"""The board's row filters (plan 23 S2): archived, ``top`` (top-level runs
only, the Jobs view: ``True`` all of them, ``"jobs"`` those with children,
``"singles"`` those without, plan 23 S7), ``scope`` (a run's subtree without the run),
``children_of`` (a run's direct children, the tree's pages, plan 28 N6), the
status whitelist and the query language, as one hashable :class:`Filters`
the cached orders are keyed by.

A row is in a scope when the scope is on its parent chain (the snapshot's
``edges``); a scoped order is built from the scope's subtree alone
(:func:`scope_positions`), so a 5000-run job costs 5000 rows, not the app,
and a children order from the children alone (:func:`narrowed_slots`).
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


Filters = namedtuple("Filters", "sort status query order archived scope top children_of",
                     defaults=(None, None, None, None, False, None, False, None))


def _child_of(row, parent):
    return row.get("parent") == parent and row["verstr"] != parent


def filtered(snapshot, rows, f):
    """*rows* of *snapshot* passing the filters *f* (``sort``/``order`` unused)."""
    rows = visible(rows, f.archived)
    if f.top:
        rows = [row for row in rows if is_top(row, f.top)]
    if f.scope is not None:
        edges = snapshot.edges
        rows = [row for row in rows if f.scope in ancestors(row["verstr"], edges)]
    if f.children_of is not None:
        rows = [row for row in rows if _child_of(row, f.children_of)]
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


def check_filters(base, f):
    """:func:`check_scope` of *f*'s ``scope`` and ``children_of``."""
    check_scope(base, f.scope)
    check_scope(base, f.children_of)


def check_scope(base, scope):
    """Known: a run of *base*, or a parent its runs name (a loading index can
    hold an outer run's inner runs before the outer run itself)."""
    if scope is not None and scope not in base.position and not base.children_of.get(scope):
        raise UnknownScope(f"no run {scope!r}")


def _positions(base, key, verstrs):
    """Storage indexes of *verstrs()* in storage order, memoized on *base* by *key*."""
    found = base.scopes.get(key)
    if found is None:
        position = base.position
        found = base.scopes[key] = sorted(position[v] for v in verstrs() if v in position)
    return found


def scope_positions(base, scope):
    """Storage indexes of *scope*'s subtree without it, in storage order."""
    return _positions(base, scope, lambda: subtree_verstrs(scope, base.children_of)[1:])


def children_positions(base, parent):
    """Storage indexes of *parent*'s direct children, in storage order."""
    return _positions(base, ("children", parent), lambda: base.children_of.get(parent, ()))


def narrowed_slots(base, f):
    """The storage indexes the rows passing *f* are among, in storage order
    (*f*'s children's, else its scope's), or None when *f* narrows nothing."""
    if f.children_of is not None:
        return children_positions(base, f.children_of)
    return scope_positions(base, f.scope) if f.scope else None
