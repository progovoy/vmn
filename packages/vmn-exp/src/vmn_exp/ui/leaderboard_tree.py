#!/usr/bin/env python3
"""A generation's tree fields derived from the previous generation's.

:func:`~vmn_exp.core.tree.annotate_rows` folds every row into the run tree.
Between two index generations only a few rows change, and only they, their
old and new parents, everything above those (``tree_status``) and everything
below a re-linked run (``depth``) or a run whose closing flips (``settled``,
:mod:`~vmn_exp.ui.leaderboard_settled`) can answer differently. :func:`derive_tree`
recomputes exactly those, rolling ``tree_status`` up from per-parent counts
of the children's ``tree_status`` (:func:`tree_index`) — so a sweep with
thousands of children costs O(changed children), not O(children).

The rollup is exact for a forest. A parent cycle reached from a changed row
makes :func:`derive_tree` answer None and the caller annotates from scratch.
"""
from vmn_exp.core.settle import row_closes
from vmn_exp.core.tree import (
    INNER,
    OUTER,
    SINGLE,
    ancestors,
    children_by_parent,
    count_statuses,
    own_rollup_status,
    rollup_status,
    sweep_trial_count,
)
from vmn_exp.ui.leaderboard_settled import resettled


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


def _depths(seeds, edges, children_of):
    """``{verstr: (depth, root)}`` for *seeds* and everything below them."""
    depth = {}
    for seed in seeds:
        if seed in depth:
            continue
        chain = ancestors(seed, edges)
        stack = [(seed, len(chain), chain[-1] if chain else None)]
        while stack:
            verstr, d, root = stack.pop()
            depth[verstr] = d, root
            stack.extend((kid, d + 1, root or verstr)
                         for kid in children_of.get(verstr, ()) if kid not in depth)
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
    changed_settled = _resettle(prev, edges, position, set(fresh) | set(moved_under), was,
                                children_of)
    above = _upward(changed_settled - dirty, edges, position)
    if above is None:
        return None
    dirty |= above
    trials = _sweep_trials(dirty, was, children_of)
    tree_status, counts = _roll_up(prev, edges, dirty | relinked, dirty, was, (children_of, trials))
    rows, rebuilt = _assemble(prev, snapshot, position, (children_of, depth, tree_status, trials),
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


def _resettle(prev, edges, position, seeds, was, children_of):
    """The rows whose ``settled`` changed (or that are fresh); their new
    values go into *was*."""
    def parent_of(verstr):
        parent = parent_in(edges, verstr)
        return parent if parent in position else None

    def was_closed(verstr):
        return verstr in prev.position and row_closes(was.old(verstr))

    resettled(seeds, was, parent_of, children_of, was_closed)
    return {v for v, s in was.settled.items()
            if v in seeds or v not in prev.position or was.old(v).get("settled") != s}


class _Was:
    """A row's fields as they stand before its tree fields are redone;
    ``settled`` holds the re-settled rows' new values."""

    def __init__(self, prev, fresh, depth):
        self._prev, self._fresh, self._depth = prev, fresh, depth
        self.settled = {}

    def settled_of(self, verstr):
        return self.settled[verstr] if verstr in self.settled else self.row(verstr).get("settled")

    def old(self, verstr):
        return self._prev.rows[self._prev.position[verstr]]

    def row(self, verstr):
        return self._fresh.get(verstr) or self.old(verstr)

    def depth(self, verstr):
        return self._depth[verstr][0] if verstr in self._depth else self.old(verstr)["depth"]

    def root(self, verstr):
        return self._depth[verstr][1] if verstr in self._depth else self.old(verstr)["root"]


def _sweep_trials(dirty, was, children_of):
    """``{verstr: sweep_trials}`` of the *dirty* sweep rows (a planned size)."""
    return {
        v: sweep_trial_count(was.row(c) for c in children_of.get(v, ()))
        for v in dirty if was.row(v).get("sweep_planned") is not None
    }


def _roll_up(prev, edges, withdrawn, dirty, was, tree):
    """``({verstr: tree_status} for *dirty*, new child status counts)``: the
    *withdrawn* rows' old statuses leave their old parents' counts, then the
    dirty rows roll up bottom-up and join their new parents'. *tree* is
    ``(children_of, {verstr: sweep_trials})``."""
    children_of, trials = tree
    counts = _Counts(prev.child_statuses)
    for verstr in withdrawn:
        parent = parent_in(prev.snapshot.edges, verstr)
        if parent and verstr in prev.position:
            counts.add(parent, was.old(verstr)["tree_status"], -1)
    tree_status = {}
    for verstr in sorted(dirty, key=was.depth, reverse=True):
        row = was.row(verstr)
        incomplete = verstr in trials and trials[verstr] < row["sweep_planned"]
        own = own_rollup_status(row["status"], bool(children_of.get(verstr)), incomplete,
                                was.settled_of(verstr))
        status = tree_status[verstr] = rollup_status({own, *counts.statuses(verstr)})
        if parent_in(edges, verstr):
            counts.add(parent_in(edges, verstr), status, 1)
    return tree_status, counts.counts


def _assemble(prev, snapshot, position, tree, fresh, touched, was):
    """``(rows, rebuilt)``: *prev*'s rows with every row whose fields changed
    replaced by a new object (the *fresh* ones completed in place). Every row
    below a re-linked run is new too: its ancestry changed, so a scoped order
    (plan 23 S2) must place it again."""
    children_of, depth, tree_status, trials = tree
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
            "root": was.root(verstr),
            "settled": was.settled_of(verstr),
            "tree_status": tree_status[verstr] if verstr in tree_status else row["tree_status"],
            "child_counts": count_statuses(was.row(c)["status"] for c in children),
        }
        if verstr in trials:
            fields["sweep_trials"] = trials[verstr]
        if verstr in fresh:
            row.update(fields)
        elif verstr in touched or verstr in depth or _tree_fields_changed(row, fields):
            row = {**row, **fields}
        else:
            continue
        rows[position[verstr]] = row
        rebuilt.add(verstr)
    return rows, rebuilt


def _tree_fields_changed(row, fields):
    return any(row.get(key) != fields.get(key)
               for key in ("depth", "root", "settled", "tree_status", "child_counts",
                           "sweep_trials"))
