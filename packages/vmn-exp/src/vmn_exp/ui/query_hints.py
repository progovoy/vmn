#!/usr/bin/env python3
"""Why a query matched nothing (plan 31 §4.2): ``kind = "launch"`` compares
the built-in row field, so a run tagged ``kind: launch`` never matches it.
When a query answers no row, each ``<row field> = <value>`` it requires
(through ``and``/``or``, never under ``not``) whose value some row carries
as ``tags.<field>`` or ``params.<field>`` gets a "did you mean" line, read
from the facet counts, never from a row pass."""
import json

from vmn_exp.core.query import ROW_FIELDS, QueryError, parse_query

SUGGESTED = ("tags", "params")


def row_equalities(text):
    """``(field, value)`` of each row-field equality *text* requires."""
    try:
        node = parse_query(text) if text and text.strip() else None
    except QueryError:
        return []
    return list(_equalities(node)) if node else []


def _equalities(node):
    if node[0] in ("and", "or"):
        for term in node[1]:
            yield from _equalities(term)
    elif node[0] == "cmp" and node[2] == "=" and node[3] is not None:
        kind, keys = node[1][:2]
        if kind == "path" and len(keys) == 1 and keys[0] in ROW_FIELDS:
            yield keys[0], node[3]


def hints(texts, counts):
    """The hint lines for queries *texts* that matched nothing, over the
    :class:`~vmn_exp.ui.leaderboard_facets.FacetCounts` *counts*."""
    out = []
    for text in texts:
        for field, value in row_equalities(text):
            prefix = next((p for p in SUGGESTED if counts.may_carry(p, field, value)), None)
            line = prefix and (f"{field} = {json.dumps(value)} matches nothing; "
                               f"did you mean {prefix}.{field}?")
            if line and line not in out:
                out.append(line)
    return out
