#!/usr/bin/env python3
"""A group's ``clause`` (plan 23 S7): the query text (:mod:`vmn_exp.core.query`)
selecting the group's rows in the view it was grouped in, so a big group
opens as a filter: ``params.lr = 0.01``, ``branch = "main"``,
``params."odd key" = "a"``, ``params.lr = null`` for the no-value group.

The value is a member row's, so its type is kept (``0.01``, ``true``,
``"0.01"``). None when the language cannot say it: a loose group, a list
or dict value, a non-finite number, text holding both quote characters.
Values whose texts coincide across types (``1`` and ``1.0``, ``1`` and
``"1"``) share a group key but not a clause: the clause matches the first
row's value.
"""
import math

from vmn_exp.ui.leaderboard_group_fields import DICT_FIELDS, NONE


def _quoted(text):
    for quote in '"\'':
        if quote not in text:
            return f"{quote}{text}{quote}"
    return None


def literal(value):
    """*value* as a query literal, or None."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else None
    if isinstance(value, str):
        return _quoted(value)
    return None


def field(group):
    """*group*'s field as the query spells it, or None."""
    prefix, dot, name = group.partition(".")
    if not dot or prefix not in DICT_FIELDS:
        return group
    if all(c.isalnum() or c == "_" for c in name):
        return group
    key = _quoted(name)
    return key and f"{prefix}.{key}"


def _value(group, row):
    prefix, dot, name = group.partition(".")
    if dot and prefix in DICT_FIELDS:
        return (row.get(prefix) or {}).get(name)
    return row.get(group)


def clause(group, key, row, loose):
    """The clause of *group*'s group *key*, *row* one of its rows."""
    name = field(group)
    if loose or name is None:
        return None
    if key == NONE:
        if group.partition(".")[0] in DICT_FIELDS:
            return f"{name} = null"
        return f'({name} = null or {name} = "")'  # key_of: no value or ""
    text = literal(_value(group, row))
    return text and f"{name} = {text}"
