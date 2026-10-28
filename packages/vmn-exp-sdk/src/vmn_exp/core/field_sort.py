#!/usr/bin/env python3
"""Sorting rows by a row field, ``tags.<k>`` or ``params.<k>`` (plan 28 FS).

A field sort ranks a row by its value there: numbers (bools as 0/1) before
strings, each in their natural order; a missing value, a non-finite number
or a list/dict ranks no row, which then goes last whichever the direction.
The row fields are the query language's (:data:`~vmn_exp.core.query.ROW_FIELDS`)
but the dates and ``idx`` (their own sorts, :data:`~vmn_exp.core.log.DATE_SORTS`)
and what a lean row lacks (``intent``, ``keywords``).
"""
import functools

from vmn_exp.core.query import ROW_FIELDS
from vmn_exp.core.values import is_finite_number

PREFIXES = ("tags", "params")
SORT_FIELDS = ROW_FIELDS - {"timestamp", "started_at", "finished_at", "idx",
                            "intent", "keywords"}


def ranked_value(value):
    """``(0, number)`` / ``(1, text)`` of a sortable *value*, else None."""
    if isinstance(value, bool):
        return 0, int(value)
    if is_finite_number(value):
        return 0, value
    if isinstance(value, str):
        return 1, value
    return None


class FieldSort:
    """One field sort: *path* is ``(field,)`` or ``(prefix, key)``."""

    def __init__(self, path):
        self.path = path

    def raw(self, row):
        """The row's value at the path when it is sortable, else None."""
        value = row.get(self.path[0])
        if len(self.path) == 2:
            value = value.get(self.path[1]) if isinstance(value, dict) else None
        return value if ranked_value(value) is not None else None

    def value(self, row):
        """:func:`ranked_value` of the row's value (None: ranks last)."""
        return ranked_value(self.raw(row))

    def placed(self, value):
        """A row holding *value* at the path (a cursor's sort target)."""
        if len(self.path) == 2:
            return {self.path[0]: {self.path[1]: value}}
        return {self.path[0]: value}


@functools.lru_cache(maxsize=256)
def field_sort(sort):
    """The :class:`FieldSort` *sort* names, or None (a metric, a date ...)."""
    if not sort:
        return None
    if sort in SORT_FIELDS:
        return FieldSort((sort,))
    prefix, dot, key = sort.partition(".")
    if dot and key and prefix in PREFIXES:
        return FieldSort((prefix, key))
    return None


def sort_by_field(rows, field, descending=False):
    """*rows* ordered by the :class:`FieldSort` *field* (stable), unranked last."""
    ranked = [r for r in rows if field.value(r) is not None]
    ranked.sort(key=field.value, reverse=bool(descending))
    return ranked + [r for r in rows if field.value(r) is None]
