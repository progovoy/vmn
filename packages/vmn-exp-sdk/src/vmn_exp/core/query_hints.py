#!/usr/bin/env python3
"""Why a query matched nothing (plan 31 §4.2): ``kind = "launch"`` compares
the built-in row field, so a run tagged ``kind: launch`` never matches it.
When a query answers no row, each ``<row field> = <value>`` it requires
(through ``and``/``or``, never under ``not``) whose value some row carries
as ``tags.<field>`` or ``params.<field>`` gets a "did you mean" line. The
caller says where a value is carried: the board from its facet counts, the
CLI from its rows."""
import json

from vmn_exp.core.query import ROW_FIELDS, QueryError, parse_query

SUGGESTED = ("tags", "params")


def row_equalities(text):
    """``(field, value)`` of each row-field equality *text* requires."""
    if not text or not text.strip():
        return []
    try:
        return list(_equalities(parse_query(text)))
    except QueryError:
        return []


def _equalities(node):
    if node[0] in ("and", "or"):
        for term in node[1]:
            yield from _equalities(term)
    elif node[0] == "cmp" and node[2] == "=" and node[3] is not None:
        kind, keys = node[1][:2]
        if kind == "path" and len(keys) == 1 and keys[0] in ROW_FIELDS:
            yield keys[0], node[3]


def hints(texts, carries):
    """The hint lines for queries *texts* that matched nothing;
    *carries(prefix, field, value)* says whether some row's ``tags``/``params``
    (*prefix*) holds *value* at *field*."""
    out = {}
    for text in texts:
        for field, value in row_equalities(text):
            prefix = next((p for p in SUGGESTED if carries(p, field, value)), None)
            if prefix:
                out.setdefault(f"{field} = {json.dumps(value)} matches nothing; "
                               f"did you mean {prefix}.{field}?")
    return list(out)
