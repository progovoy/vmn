#!/usr/bin/env python3
"""Nesting for experiments: outer jobs (sweeps, orchestrators) and the inner
jobs they spawn.

An experiment records the verstr of the run that launched it in its metadata as
``parent``. This module folds a flat list of rows into that shape — who has
children, how deep a run sits, and what an outer job's *effective* status is
once its whole subtree is taken into account.

Pure: rows in, new rows out, no storage. :func:`subtree_status` reads run
states only through the reader its caller passes in.
"""
from version_stamp.core.experiment_status import (
    CREATED,
    FAILED,
    RUNNING,
    STUCK,
    SUCCEEDED,
    derive_status,
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


def children_by_parent(nodes):
    """``{parent verstr: [child verstr]}`` — a run is never its own child."""
    children_of = {}
    for node in nodes:
        parent = node.get("parent")
        if parent and parent != node["verstr"]:
            children_of.setdefault(parent, []).append(node["verstr"])
    return children_of


def subtree_verstrs(verstr, children_of):
    """*verstr* and everything below it, cycle-safe."""
    seen, stack, out = set(), [verstr], []
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        out.append(current)
        stack.extend(children_of.get(current, []))
    return out


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

    children_of = children_by_parent(rows)

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


TREE_FIELDS = ("children", "kind", "depth", "tree_status")


def subtree_status(verstr, parent_of, read_state):
    """``(run_state, tree_fields)`` for one run, reading its subtree's states only.

    *parent_of* is ``{verstr: parent}`` for the app's runs; *read_state(verstr)*
    returns a raw run state and is called once per subtree member. Ancestors
    are placed in the tree (for ``depth``) but never read.
    """
    children_of = children_by_parent(
        [{"verstr": v, "parent": p} for v, p in parent_of.items()]
    )
    ordered = subtree_verstrs(verstr, children_of)
    subtree = set(ordered)
    nodes = {v: parent_of.get(v) for v in ordered}
    cursor = parent_of.get(verstr)
    while cursor and cursor not in nodes:
        nodes[cursor] = parent_of.get(cursor)
        cursor = nodes[cursor]

    rows, run_state = [], None
    for node, parent in nodes.items():
        row = {"verstr": node, "parent": parent}
        if node in subtree:
            state = read_state(node)
            row["status"] = derive_status(state)
            if node == verstr:
                run_state = state
        rows.append(row)

    tree = next(r for r in annotate_tree(rows) if r["verstr"] == verstr)
    return run_state, {k: tree[k] for k in TREE_FIELDS}
