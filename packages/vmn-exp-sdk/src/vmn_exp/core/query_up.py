#!/usr/bin/env python3
"""Ancestor fields (plan 28 N1): what ``up.params.<k>`` and
``up(tags.kind = "study").params.<k>`` read of a run's parent chain.

A field node is ``("up", selector, keys)``: *keys* the path read
(``("params", k)``, ``("tags", k)`` or ``("name",)``) and *selector* None
(the nearest ancestor holding a non-null value there) or ``(keys, literal)``
(the nearest ancestor whose value there equals *literal*; the field is then
read from it, missing when it lacks it). The chain is the parent links,
nearest first: a run never reads itself, a parent missing from the rows
ends it and a cycle stops where it closes.

:class:`AncestorFields` memoizes, per field, the answer at or above each
ancestor it walked, so a generation costs one read per ancestor and field
however many runs sit below it. :func:`ancestor_fields` keeps one per index
snapshot; the next generation starts afresh.
"""
import functools
import weakref

from vmn_exp.core.tree import parent_map

UP = "up"
# What an ``up.`` field and a selector may read: fields every run's stored
# row carries, whatever view of a snapshot it came from.
UP_PREFIXES = ("params", "tags")
UP_FIELDS = ("name",)
# Fields memoized per snapshot before the memo starts over.
MAX_FIELDS = 16


def readable(keys):
    """Whether an ``up`` field (or a selector) may read the path *keys*."""
    if len(keys) == 2:
        return keys[0] in UP_PREFIXES
    return len(keys) == 1 and keys[0] in UP_FIELDS


def dig(row, keys):
    """The value at path *keys* in the nested dicts of *row*, or None."""
    for key in keys:
        row = (row or {}).get(key)
    return row


def equal(left, right):
    """The query language's ``=``: None only equals None, a bool only a bool."""
    if right is None:
        return left is None
    if left is None or isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _holds(row, selector, keys):
    if selector is None:
        return dig(row, keys) is not None
    sel_keys, literal = selector
    return equal(dig(row, sel_keys), literal)


def up_view(row):
    """What any ``up`` field reads of *row*."""
    return None if row is None else tuple(row.get(k) for k in UP_PREFIXES + UP_FIELDS)


class AncestorFields:
    """``up`` field values over a parent map (``{verstr: parent}``) and a
    ``verstr -> row or None`` reader."""

    def __init__(self, parent_of, row_of):
        self._parent_of, self._row_of = parent_of, row_of
        self._memo = {}  # {(selector, keys): {verstr: (holder, value) at or above it}}

    def value(self, verstr, node):
        """*verstr*'s value of the ``up`` field *node*, or None."""
        _, selector, keys = node
        parent = self._parent_of.get(verstr)
        if not parent or parent == verstr:
            return None
        memo = self._field_memo((selector, keys))
        holder, value = memo.get(parent) or self._at_or_above(memo, parent, selector, keys)
        return None if holder == verstr else value

    def of(self, verstr):
        """``node -> value`` for *verstr* (what a query row reads as ``up``)."""
        return functools.partial(self.value, verstr)

    def _at_or_above(self, memo, verstr, selector, keys):
        """``(holder, value)`` at or above *verstr*, filling *memo* on the way
        (the walk of :func:`~vmn_exp.core.tree.ancestors`, *verstr* first)."""
        path, seen, cursor, found = [], set(), verstr, (None, None)
        while cursor and cursor not in seen:
            if cursor in memo:
                found = memo[cursor]
                break
            seen.add(cursor)
            path.append(cursor)
            row = self._row_of(cursor)
            if row is not None and _holds(row, selector, keys):
                found = (cursor, dig(row, keys))
                break
            cursor = self._parent_of.get(cursor)
        for walked in path:
            memo[walked] = found
        return found

    def _field_memo(self, field):
        memo = self._memo.get(field)
        if memo is None:
            if len(self._memo) >= MAX_FIELDS:
                self._memo.clear()
            memo = self._memo.setdefault(field, {})
        return memo


def rows_ancestor_fields(rows):
    """:class:`AncestorFields` over *rows* and their own ``parent`` links."""
    return AncestorFields(parent_map(rows), {row["verstr"]: row for row in rows}.get)


def ancestor_fields(snapshot):
    """*snapshot*'s :class:`AncestorFields` (its ``parent_of`` and rows),
    one per snapshot when it keeps a memo (an index snapshot does). The memo
    reads the rows through a weak reference: no cycle keeps a snapshot alive."""
    memo = getattr(snapshot, "_up", None)
    if memo is None:
        return AncestorFields(snapshot.parent_of, snapshot.row)
    if not memo:
        ref = weakref.ref(snapshot)
        memo.append(AncestorFields(snapshot.parent_of, lambda verstr: ref().row(verstr)))
    return memo[0]

