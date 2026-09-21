#!/usr/bin/env python3
"""Nesting for experiments: outer jobs (sweeps, orchestrators) and the inner
jobs they spawn.

An experiment records the verstr of the run that launched it in its metadata as
``parent``. This module folds a flat list of rows into that shape — who has
children, how deep a run sits, and what an outer job's *effective* status is
once its whole subtree is taken into account.

Pure: rows in, new rows out, no storage and no clock.
"""
from version_stamp.core.experiment_status import (
    CREATED,
    FAILED,
    RUNNING,
    STUCK,
    SUCCEEDED,
)

OUTER = "outer"  # has children
INNER = "inner"  # has a parent
SINGLE = "single"  # neither

# What a mixed subtree reports. A single failure is the headline; an unfinished
# run outranks a clean one, because the subtree isn't done yet.
_PRECEDENCE = (FAILED, STUCK, RUNNING, CREATED, SUCCEEDED)


def rollup_status(statuses):
    """The single status that best describes a set of runs, or None if empty."""
    statuses = {s for s in statuses if s}
    return next((c for c in _PRECEDENCE if c in statuses), None)


def _depth(verstr, parent_of):
    """Distance to the top of the parent chain. A cycle stops at its entry point."""
    depth = 0
    seen = {verstr}
    cursor = verstr
    while True:
        parent = parent_of.get(cursor)
        if not parent or parent in seen:
            return depth
        depth += 1
        seen.add(parent)
        cursor = parent


def _subtree_statuses(verstr, children_of, by_verstr, seen=None):
    seen = seen if seen is not None else set()
    if verstr in seen:
        return []
    seen.add(verstr)
    statuses = [(by_verstr.get(verstr) or {}).get("status")]
    for child in children_of.get(verstr, []):
        statuses.extend(_subtree_statuses(child, children_of, by_verstr, seen))
    return statuses


def annotate_tree(rows):
    """Add ``children``, ``kind``, ``depth`` and ``tree_status`` to each row.

    ``status`` is left as the row's own status; ``tree_status`` is the rollup
    over the row and everything beneath it.
    """
    rows = [dict(r) for r in rows]
    by_verstr = {r["verstr"]: r for r in rows}
    parent_of = {r["verstr"]: r.get("parent") for r in rows if r.get("parent")}

    children_of = {}
    for row in rows:
        parent = row.get("parent")
        if parent and parent != row["verstr"]:
            children_of.setdefault(parent, []).append(row["verstr"])

    for row in rows:
        verstr = row["verstr"]
        children = children_of.get(verstr, [])
        row["children"] = children
        if children:
            row["kind"] = OUTER
        elif row.get("parent"):
            row["kind"] = INNER
        else:
            row["kind"] = SINGLE
        row["depth"] = _depth(verstr, parent_of)
        row["tree_status"] = rollup_status(
            _subtree_statuses(verstr, children_of, by_verstr)
        )
    return rows
