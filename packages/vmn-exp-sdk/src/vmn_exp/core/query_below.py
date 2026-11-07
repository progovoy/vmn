#!/usr/bin/env python3
"""The query's :data:`~vmn_exp.core.query.BELOW_FIELDS`: how many runs below
a row still run, wait or are stuck (``live_below``), or run or are stuck
alone (``running_below``/``stuck_below``), how many failed or were lost
(``failed_below``) and their share of the runs below it in percent
(``failed_pct``, the Jobs view rollup's, plan 31 §1) — 0 for a run without
children.

A run counts by its :func:`~vmn_exp.core.settle.counted_status` (a
never-started one does not wait, a lost one is done and failed; an outlived
one runs) in each run up its parent chain, up to its nearest archived one:
an archived run counts its own subtree, the runs above it do not, and an
archived run counts nowhere — the Jobs view rollup's membership rule.

:func:`below_extra` is :func:`~vmn_exp.core.query.filter_rows`' *extra* for
them over every annotated row of an app (every snapshot extra of
:mod:`~vmn_exp.core.query_extra` carries it): the counts are taken once, on the
first read, so a query not reading them costs nothing; one reading a live
count costs a pass over the rows plus a parent walk per live run, one
reading ``failed_below``/``failed_pct`` a parent walk per run.
"""
from functools import cache

from vmn_exp.core.query import LIVE_BELOW_FIELDS
from vmn_exp.core.settle import LOST, SETTLED, counted_status
from vmn_exp.core.status import CREATED, FAILED, RUNNING, STUCK, SUCCEEDED
from vmn_exp.core.tree import counted_chain, parent_map

# Each of the live BELOW_FIELDS and the counted statuses it sums.
BELOW_STATES = {"live_below": (RUNNING, CREATED, STUCK),
                "running_below": (RUNNING,), "stuck_below": (STUCK,)}
assert BELOW_STATES.keys() == LIVE_BELOW_FIELDS
_LIVE = frozenset(BELOW_STATES["live_below"])
# Each live counted status and the fields it counts in.
_FIELDS_OF = {s: [f for f, states in BELOW_STATES.items() if s in states] for s in _LIVE}
# Every status a rollup counts, and those failed_below counts: a lost run
# finished failed.
_COUNTED = frozenset((RUNNING, CREATED, STUCK, SUCCEEDED, FAILED, *SETTLED))
_FAILED = frozenset((FAILED, LOST))


def _count_up(rows, tables_of):
    """Add each of *rows* to the ``{verstr: n}`` *tables_of(its counted
    status)* of every run it counts in."""
    parent_of = parent_map(rows)
    archived = {row["verstr"] for row in rows if row.get("archived")}
    for row in rows:
        tables = tables_of(None if row.get("archived") else counted_status(row))
        if tables:
            for up in counted_chain(row["verstr"], parent_of, archived.__contains__):
                for table in tables:
                    table[up] = table.get(up, 0) + 1


def below_counts(rows):
    """``{field: {verstr: n}}`` of the live runs below each of *rows*, per
    one of the live :data:`BELOW_STATES`."""
    counts = {field: {} for field in BELOW_STATES}
    tables = {s: [counts[field] for field in fields] for s, fields in _FIELDS_OF.items()}
    _count_up(rows, tables.get)
    return counts


def failed_counts(rows):
    """``({verstr: runs below}, {verstr: failed or lost runs below})`` of *rows*."""
    total, failed = {}, {}

    def tables_of(status):
        if status in _FAILED:
            return total, failed
        return (total,) if status in _COUNTED else ()

    _count_up(rows, tables_of)
    return total, failed


def failed_share(failed, total):
    """*failed* of *total* runs in percent (2 decimals), 0 of none."""
    return round(100 * failed / total, 2) if total else 0.0


def lazy_below_extra(rows_of):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over the rows
    *rows_of()* returns, called on the first read."""
    rows = cache(rows_of)
    counted = cache(lambda: below_counts(rows()))
    failed = cache(lambda: failed_counts(rows()))
    extra = {field: (lambda verstr, field=field: counted()[field].get(verstr, 0))
             for field in BELOW_STATES}
    extra["failed_below"] = lambda verstr: failed()[1].get(verstr, 0)
    extra["failed_pct"] = lambda verstr: failed_share(failed()[1].get(verstr, 0),
                                                       failed()[0].get(verstr, 0))
    return extra


def below_extra(rows):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over *rows*."""
    return lazy_below_extra(lambda: rows)
