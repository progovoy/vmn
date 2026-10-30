#!/usr/bin/env python3
"""The query's :data:`~vmn_exp.core.query.BELOW_FIELDS`: how many runs below
a row still run, wait or are stuck (``live_below``), or run or are stuck
alone (``running_below``/``stuck_below``) — 0 for a run without children.

A run counts by its :func:`~vmn_exp.core.settle.counted_status` (settled runs
never: a never-started one does not wait, a lost one is done; an outlived
one runs) in each run up its parent chain, up to its nearest archived one:
an archived run counts its own subtree, the runs above it do not, and an
archived run counts nowhere — the Jobs view rollup's membership rule.

:func:`below_extra` is :func:`~vmn_exp.core.query.filter_rows`' *extra* for
them over every annotated row of an app (every snapshot extra of
:mod:`~vmn_exp.core.query_extra` carries it): the counts are taken once, on the
first read, so a query not reading them costs nothing; one that does costs
a pass over the rows plus a parent walk per live run.
"""
from functools import cache

from vmn_exp.core.query import BELOW_FIELDS
from vmn_exp.core.settle import counted_status
from vmn_exp.core.status import CREATED, RUNNING, STUCK
from vmn_exp.core.tree import counted_chain, parent_map

# Each of the BELOW_FIELDS and the counted statuses it sums.
BELOW_STATES = {"live_below": (RUNNING, CREATED, STUCK),
                "running_below": (RUNNING,), "stuck_below": (STUCK,)}
assert BELOW_STATES.keys() == BELOW_FIELDS
_LIVE = frozenset(BELOW_STATES["live_below"])
# Each live counted status and the fields it counts in.
_FIELDS_OF = {s: [f for f, states in BELOW_STATES.items() if s in states] for s in _LIVE}


def below_counts(rows):
    """``{field: {verstr: n}}`` of the live runs below each of *rows*, per
    one of the :data:`BELOW_FIELDS`."""
    parent_of = parent_map(rows)
    archived = {row["verstr"] for row in rows if row.get("archived")}
    counts = {field: {} for field in BELOW_STATES}
    for row in rows:
        status = None if row.get("archived") else counted_status(row)
        if status in _LIVE:
            tables = [counts[field] for field in _FIELDS_OF[status]]
            for up in counted_chain(row["verstr"], parent_of, archived.__contains__):
                for table in tables:
                    table[up] = table.get(up, 0) + 1
    return counts


def lazy_below_extra(rows_of):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over the rows
    *rows_of()* returns, called on the first read."""
    counted = cache(lambda: below_counts(rows_of()))
    return {field: (lambda verstr, field=field: counted()[field].get(verstr, 0))
            for field in BELOW_STATES}


def below_extra(rows):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over *rows*."""
    return lazy_below_extra(lambda: rows)
