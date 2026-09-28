#!/usr/bin/env python3
"""A generation's tree fields derived from the previous generation's.

:func:`~vmn_exp.core.tree.annotate_rows` folds every row into the run tree.
Between two index generations only a few rows change, and only they, their
old and new parents, everything above those (``tree_status``) and everything
below a re-linked run (``depth``) can answer differently. :func:`derive_tree`
recomputes exactly those, rolling ``tree_status`` up from per-parent counts
of the children's ``tree_status`` (:func:`tree_index`) — so a sweep with
thousands of children costs O(changed children), not O(children).

The rollup is exact for a forest. A parent cycle reached from a changed row
makes :func:`derive_tree` answer None and the caller annotates from scratch.
"""
from vmn_exp.core.tree import INNER, OUTER, SINGLE, _depth, children_by_parent, rollup_status


def parent_in(edges, verstr):
    """*verstr*'s parent for tree purposes — never itself — or None."""
    parent = edges.get(verstr)
    return parent if parent and parent != verstr else None


def kind_of(row, children):
    if children:
        return OUTER
    return INNER if row.get("parent") else SINGLE


def tree_index(rows):
    """``(children_of, child_statuses)`` of annotated *rows*: the children
    lists ``annotate_rows`` built and ``{parent: {tree_status: count}}``."""
    children_of = children_by_parent(rows)
    status_of = {row["verstr"]: row["tree_status"] for row in rows}
    counts = {}
    for parent, kids in children_of.items():
        tally = counts[parent] = {}
        for kid in kids:
            tally[status_of[kid]] = tally.get(status_of[kid], 0) + 1
    return children_of, counts


class _Counts:
    """Copy-on-write ``{parent: {tree_status: count}}``."""

    def __init__(self, counts):
        self.counts = dict(counts)
        self._owned = set()

    def add(self, parent, status, by):
        if parent not in self._owned:
            self.counts[parent] = dict(self.counts.get(parent, {}))
            self._owned.add(parent)
        tally = self.counts[parent]
        count = tally.get(status, 0) + by
        if count:
            tally[status] = count
        else:
            tally.pop(status, None)

    def statuses(self, parent):
        return self.counts.get(parent, {}).keys()


def _upward(seeds, edges, position):
    """*seeds* and every row above them, or None if a parent chain loops."""
    closed = set()
    for seed in seeds:
        path, cursor = [], seed
        while cursor is not None and cursor not in closed:
            if cursor in path:
                return None
            path.append(cursor)
            parent = parent_in(edges, cursor)
            cursor = parent if parent in position else None
        closed.update(path)
    return closed


def _depths(roots, edges, children_of):
    """``{verstr: depth}`` for *roots* and everything below them."""
    depth = {}
    for root in roots:
        if root in depth:
            continue
        stack = [(root, _depth(root, edges))]
        while stack:
            verstr, d = stack.pop()
            depth[verstr] = d
            stack.extend((kid, d + 1) for kid in children_of.get(verstr, ()) if kid not in depth)
    return depth


def _joined(relinked, edges, position):
    """``{parent: [child]}`` of the *relinked* runs still present, in storage order."""
    joined = {}
    for verstr in sorted(relinked & position.keys(), key=position.__getitem__):
        parent = parent_in(edges, verstr)
        if parent:
            joined.setdefault(parent, []).append(verstr)
    return joined


def derive_tree(prev, snapshot, fresh, gone, position):
    """``(rows, children_of, child_statuses, rebuilt)`` for *snapshot*, or None.

    *prev* is the previous generation's base (``snapshot``, ``rows``,
    ``position``, ``children_of``, ``child_statuses``); *fresh* is ``{verstr:
    row with its status fields}`` for every changed or live row, *gone* the
    verstrs that left, *position* the new ``{verstr: storage index}``.
    Unchanged rows must keep their storage index. *rebuilt* names the rows
    that are new objects.
    """
    edges = snapshot.edges
    relinked = set(gone) | {
        v for v in fresh
        if prev.position.get(v) != position[v]
        or parent_in(prev.snapshot.edges, v) != parent_in(edges, v)
    }
    children_of, touched = _relink(prev, edges, relinked, position)
    dirty = _upward(set(fresh) | touched, edges, position)
    if dirty is None:
        return None
    moved_under = [kid for g in gone for kid in children_of.get(g, ())]
    depth = _depths(sorted(relinked & position.keys()) + moved_under, edges, children_of)
    was = _Was(prev, fresh, depth)
    tree_status, counts = _roll_up(prev, edges, dirty | relinked, dirty, was)
    rows, rebuilt = _assemble(prev, snapshot, position, (children_of, depth, tree_status),
                              fresh, touched, was)
    return rows, children_of, counts, rebuilt


def _relink(prev, edges, relinked, position):
    """``(children_of, touched)``: the new children lists, and the rows whose
    children changed."""
    left = {parent_in(prev.snapshot.edges, v) for v in relinked if v in prev.position}
    joined = _joined(relinked, edges, position)
    children_of = dict(prev.children_of)
    for parent in (left | joined.keys()) - {None}:
        kids = [k for k in prev.children_of.get(parent, ()) if k not in relinked]
        kids = sorted(kids + joined.get(parent, []), key=position.__getitem__)
        if kids:
            children_of[parent] = kids
        else:
            children_of.pop(parent, None)
    return children_of, (left | joined.keys()) & position.keys()


class _Was:
    """A row's fields as they stand before its tree fields are redone."""

    def __init__(self, prev, fresh, depth):
        self._prev, self._fresh, self._depth = prev, fresh, depth

    def old(self, verstr):
        return self._prev.rows[self._prev.position[verstr]]

    def row(self, verstr):
        return self._fresh.get(verstr) or self.old(verstr)

    def depth(self, verstr):
        return self._depth[verstr] if verstr in self._depth else self.old(verstr)["depth"]


def _roll_up(prev, edges, withdrawn, dirty, was):
    """``({verstr: tree_status} for *dirty*, new child status counts)``: the
    *withdrawn* rows' old statuses leave their old parents' counts, then the
    dirty rows roll up bottom-up and join their new parents'."""
    counts = _Counts(prev.child_statuses)
    for verstr in withdrawn:
        parent = parent_in(prev.snapshot.edges, verstr)
        if parent and verstr in prev.position:
            counts.add(parent, was.old(verstr)["tree_status"], -1)
    tree_status = {}
    for verstr in sorted(dirty, key=was.depth, reverse=True):
        own = was.row(verstr)["status"]
        status = tree_status[verstr] = rollup_status({own, *counts.statuses(verstr)})
        if parent_in(edges, verstr):
            counts.add(parent_in(edges, verstr), status, 1)
    return tree_status, counts.counts


def _assemble(prev, snapshot, position, tree, fresh, touched, was):
    """``(rows, rebuilt)``: *prev*'s rows with every row whose fields changed
    replaced by a new object (the *fresh* ones completed in place)."""
    children_of, depth, tree_status = tree
    rows = list(prev.rows[: len(snapshot.rows)])
    rows.extend([None] * (len(snapshot.rows) - len(rows)))
    rebuilt = set()
    for verstr in set(fresh) | touched | depth.keys() | tree_status.keys():
        row = was.row(verstr)
        children = children_of.get(verstr, [])
        fields = {
            "children": children,
            "kind": kind_of(row, children),
            "depth": was.depth(verstr),
            "tree_status": tree_status[verstr] if verstr in tree_status else row["tree_status"],
        }
        if verstr in fresh:
            row.update(fields)
        elif verstr in touched or (row["depth"], row["tree_status"]) != (
            fields["depth"], fields["tree_status"]
        ):
            row = {**row, **fields}
        else:
            continue
        rows[position[verstr]] = row
        rebuilt.add(verstr)
    return rows, rebuilt
