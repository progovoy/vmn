#!/usr/bin/env python3
"""What an ended outer run makes of the runs it left behind (derived, never
stored): a descendant that never started is ``never_started``, a stuck or
released one (it ran and never finished) ``lost``, a running one (still
beating) ``outlived`` — counted as running still. A run's own status stays what
:func:`~vmn_exp.core.status.derive_status` says; only its ``settled`` field
and the rollups over it change.

Statuses here are :func:`~vmn_exp.core.status.settle_status` keys: a
released run reads ``released``, which settles like a stuck one and passes
its parent's verdict on like a waiting one.

A run *closes* its children when it has ended (succeeded, failed or stuck),
or when it never started (or was released) under a closed parent — a container passes
its parent's verdict on. A running run keeps its children open: it may
still start them. Pure.
"""
from vmn_exp.core.status import (
    CREATED,
    FAILED,
    RELEASED,
    RUNNING,
    STUCK,
    SUCCEEDED,
    settle_status,
)

NEVER_STARTED = "never_started"
LOST = "lost"
OUTLIVED = "outlived"
# What a rollup counts apart from the statuses, and what closes like an end.
SETTLED = (NEVER_STARTED, LOST)
ENDED = frozenset((SUCCEEDED, FAILED, STUCK))
_SETTLED_AS = {CREATED: NEVER_STARTED, STUCK: LOST, RELEASED: LOST, RUNNING: OUTLIVED}
# Runs that pass their parent's verdict on to their own children.
_WAITING = (CREATED, RELEASED)


def settled_as(status, parent_closed):
    """``never_started``/``lost``/``outlived`` for a run of *status* under a
    closed parent, else None."""
    return _SETTLED_AS.get(status) if parent_closed else None


def row_settled_as(row, parent_closed):
    """:func:`settled_as` of a row with its status fields."""
    return settled_as(settle_status(row["status"], row.get("end_reason")), parent_closed)


def closes(status, settled=None):
    """Whether a run of *status* (and *settled*) closes its children."""
    return status in ENDED or settled in SETTLED


def row_closes(row):
    """:func:`closes` of an annotated *row*."""
    return closes(row.get("status"), row.get("settled"))


def counted_status(row):
    """What a rollup counts *row* as: see :func:`counted_as`."""
    return counted_as(row.get("status"), row.get("settled"))


def counted_as(status, settled):
    """*settled* when a rollup counts it apart (:data:`SETTLED`), else
    *status*: an outlived run counts as running."""
    return settled if settled in SETTLED else status


def split_slots(slots, closed):
    """``(waiting, never_started)`` of an outer run's *slots* not created
    yet: none will be once it is *closed*."""
    return (0, slots) if closed else (slots, 0)


def settled_runs(status_of, parent_of):
    """``{verstr: settled}`` of the runs in *status_of* an ended outer run
    settled (the others are left out). The nearest started run up a parent
    chain decides; a missing parent or a loop leaves the chain open."""
    closed = {}
    out = {}
    for verstr, status in status_of.items():
        parent = parent_of.get(verstr)
        if status in _SETTLED_AS and parent and parent != verstr:
            settled = settled_as(status, _closed(parent, status_of, parent_of, closed))
            if settled:
                out[verstr] = settled
    return out


def _closed(start, status_of, parent_of, closed):
    """Whether *start* closes its children, memoized in *closed*."""
    chain, cursor, seen = [], start, set()
    while cursor in status_of and cursor not in closed and cursor not in seen:
        seen.add(cursor)
        status = status_of[cursor]
        if status not in _WAITING:
            closed[cursor] = status in ENDED
            break
        chain.append(cursor)
        cursor = parent_of.get(cursor)
    verdict = closed.get(cursor, False)
    for verstr in chain:
        closed[verstr] = verdict
    return closed.get(start, verdict)


def subtree_settled(order, statuses, parent_of, chain, status_above):
    """``{verstr: settled}`` over *order* (a subtree, its root first, each
    run before its children). *chain* is the root's ancestors, nearest
    first; their statuses are read through *status_above(verstr)* only while
    the root (then each ancestor) never started or is stuck — what its own
    verdict needs."""
    root = order[0]
    closed = {}
    settled = {root: settled_as(statuses[root], _closed_above(statuses[root], chain, status_above))}
    for verstr in order:
        if verstr != root:
            settled[verstr] = settled_as(statuses[verstr], closed.get(parent_of.get(verstr), False))
        closed[verstr] = closes(statuses[verstr], settled[verstr])
    return settled


def _closed_above(status, chain, status_above):
    """Whether the parent of a run of *status* closes its children."""
    if status not in _SETTLED_AS:
        return False
    for ancestor in chain:
        above = status_above(ancestor)
        if above not in _WAITING:
            return above in ENDED
    return False
