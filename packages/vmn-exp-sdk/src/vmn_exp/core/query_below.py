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
them over every annotated row of an app: the counts are taken once, on the
first read, so a query not reading them costs nothing; one that does costs
a pass over the rows plus a parent walk per live run.
"""
from collections import Counter
from functools import cache

from vmn_exp.core.query import BELOW_FIELDS
from vmn_exp.core.settle import counted_status
from vmn_exp.core.status import CREATED, RUNNING, STUCK

# Each of the BELOW_FIELDS and the counted statuses it sums.
BELOW_STATES = {"live_below": (RUNNING, CREATED, STUCK),
                "running_below": (RUNNING,), "stuck_below": (STUCK,)}
assert BELOW_STATES.keys() == BELOW_FIELDS
_LIVE = frozenset(BELOW_STATES["live_below"])


def _parent(row):
    parent = row.get("parent")
    return parent if parent != row["verstr"] else None


def counted_in(row, row_of):
    """The runs above *row* it counts in, nearest first (cycle-safe)."""
    chain, seen, parent = [], {row["verstr"]}, _parent(row)
    while parent in row_of and parent not in seen:
        chain.append(parent)
        seen.add(parent)
        if row_of[parent].get("archived"):
            break
        parent = _parent(row_of[parent])
    return chain


def below_counts(rows):
    """``{verstr: Counter(counted status)}`` of the live runs below each of *rows*."""
    row_of = {row["verstr"]: row for row in rows}
    counts = {}
    for row in rows:
        status = None if row.get("archived") else counted_status(row)
        if status in _LIVE:
            for up in counted_in(row, row_of):
                counts.setdefault(up, Counter())[status] += 1
    return counts


def below_extra(rows):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over *rows*."""
    counted = cache(lambda: below_counts(rows))

    def reader(states):
        return lambda verstr: sum(counted().get(verstr, {}).get(s, 0) for s in states)

    return {field: reader(states) for field, states in BELOW_STATES.items()}
