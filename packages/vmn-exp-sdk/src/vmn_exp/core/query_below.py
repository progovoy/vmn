#!/usr/bin/env python3
"""The query's :data:`~vmn_exp.core.query.BELOW_FIELDS`: how many runs below
a row still run, wait or are stuck (``live_below``), or run or are stuck
alone (``running_below``/``stuck_below``), how many failed or were lost
(``failed_below``: what did not finish) and their share of the runs below it
in percent (``failed_pct``, the Jobs view rollup's, plan 31 §1), and how many
of those were lost (``lost_below``, plan 34 §3) — 0 for a run without
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
count or ``failed_below``/``failed_pct``/``lost_below`` costs a pass over the rows plus a
parent walk per parent of a counted run.
"""
from collections import Counter
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
# Every status a rollup counts (failed_below counts a lost run too: it did
# not finish).
_COUNTED = frozenset((RUNNING, CREATED, STUCK, SUCCEEDED, FAILED, *SETTLED))
TOTAL, FAILED_BELOW, LOST_BELOW = "total", "failed_below", "lost_below"


def _count_up(rows, fields_of, fields):
    """``{field: {verstr: n}}``: each of *rows* counted, in each of the
    *fields_of(its counted status)*, in every run it counts in. A row counts
    in its parent and wherever its parent does, so the walk is one per parent."""
    parent_of = parent_map(rows)
    archived = {row["verstr"] for row in rows if row.get("archived")}
    direct, own = {}, {}  # parent -> Counter of its rows' fields; row -> its fields
    for row in rows:
        verstr = row["verstr"]
        parent = parent_of.get(verstr)
        names = parent and parent != verstr and not row.get("archived") and fields_of(counted_status(row))
        if names:
            direct.setdefault(parent, Counter()).update(names)
            own[verstr] = names
    counts = {field: {} for field in fields}
    for parent, by_field in direct.items():
        chain = [parent, *counted_chain(parent, parent_of, archived.__contains__)]
        for up in chain:
            for field, n in by_field.items():
                counts[field][up] = counts[field].get(up, 0) + n
        for up in chain[1:]:  # a row in a parent loop never counts in itself
            if parent_of.get(up) == parent:
                for field in own.get(up, ()):
                    counts[field][up] -= 1
    return counts


def below_counts(rows):
    """``{field: {verstr: n}}`` of the live runs below each of *rows*, per
    one of the live :data:`BELOW_STATES`."""
    return _count_up(rows, lambda status: _FIELDS_OF.get(status, ()), BELOW_STATES)


def _failed_fields(status):
    if status == LOST:
        return TOTAL, FAILED_BELOW, LOST_BELOW
    if status == FAILED:
        return TOTAL, FAILED_BELOW
    return (TOTAL,) if status in _COUNTED else ()


def failed_counts(rows):
    """``{total|failed_below|lost_below: {verstr: n}}``: the runs below each
    of *rows*, the failed or lost ones, and the lost ones."""
    return _count_up(rows, _failed_fields, (TOTAL, FAILED_BELOW, LOST_BELOW))


def failed_share(failed, total):
    """*failed* of *total* runs in percent (2 decimals), 0 of none."""
    return round(100 * failed / total, 2) if total else 0.0


def lazy_below_extra(rows_of):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over the rows
    *rows_of()* returns, called on the first read."""
    rows = cache(rows_of)
    counted = cache(lambda: below_counts(rows()))
    failed = cache(lambda: failed_counts(rows()))

    def failed_pct(verstr):
        counts = failed()
        return failed_share(counts[FAILED_BELOW].get(verstr, 0), counts[TOTAL].get(verstr, 0))

    extra = {field: (lambda verstr, field=field: counted()[field].get(verstr, 0))
             for field in BELOW_STATES}
    for field in (FAILED_BELOW, LOST_BELOW):
        extra[field] = lambda verstr, field=field: failed()[field].get(verstr, 0)
    extra["failed_pct"] = failed_pct
    return extra


def below_extra(rows):
    """``{field: of(verstr)}`` for the :data:`BELOW_FIELDS` over *rows*."""
    return lazy_below_extra(lambda: rows)
