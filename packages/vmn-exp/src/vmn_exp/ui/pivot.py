#!/usr/bin/env python3
"""The pivot heatmap (plan 28 N2): filtered rows crossed by two group fields
(:mod:`~vmn_exp.ui.leaderboard_group_fields`: ``tags.<k>``, ``params.<k>``,
``up.*``, ``branch``, ``status``, ``root``, a link), one cell per pair of
values: its run count (``count``), the share of its runs matching a query
(``share``, ``match=``), or an aggregate of a metric's values (``agg``,
``metric=``, ``agg=``).

Each axis keeps its :data:`MAX_ROWS`/:data:`MAX_COLS` most populous values,
ordered by value (numbers before text, ``(none)`` last); each header and
cell carries the clause selecting its runs
(:mod:`~vmn_exp.ui.leaderboard_group_clause`), so it opens as a filter.
An empty cell is ``null``. Pure but for the snapshot an ``up`` field reads.
"""
import heapq
from collections import Counter, namedtuple

from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.leaderboard_group_clause import value_clause
from vmn_exp.ui.leaderboard_group_fields import (
    NONE,
    NONE_LABEL,
    check_aggregate,
    check_group,
    key_of,
    key_text,
    value_of,
)
from vmn_exp.ui.leaderboard_group_summary import of_sorted
from vmn_exp.ui.readers.experiments import apply_filters

MAX_ROWS = 200
MAX_COLS = 50
CELLS = ("count", "share", "agg")

PivotSpec = namedtuple("PivotSpec", "rows cols cell match metric agg status query archived scope")


def pivot_spec(rows, cols, cell="count", match=None, metric=None, agg="mean",
               status=None, query=None, archived=False, scope=None):
    """A checked :class:`PivotSpec`; ValueError on a bad field or cell."""
    if cell not in CELLS:
        raise ValueError(f"cell must be one of {', '.join(CELLS)}, not {cell!r}")
    if cell == "share" and not (match and match.strip()):
        raise ValueError("cell=share needs match=<query>")
    if cell == "agg" and not metric:
        raise ValueError("cell=agg needs metric=<name>")
    return PivotSpec(check_group(rows), check_group(cols), cell,
                     match if cell == "share" else None, metric if cell == "agg" else None,
                     check_aggregate(agg) if cell == "agg" else None,
                     status or None, query or None, bool(archived), scope)


def _value_order(key, value):
    if key == NONE:
        return (2, 0, "")
    if is_finite_number(value):
        return (0, value, key)
    return (1, 0, key)


def _axis(field, keys, first, cap):
    """``(headers, {key: position}, distinct keys)`` of the *cap* most
    populous of the rows' *keys*, ordered by value (*first*: a value per key)."""
    counts = Counter(keys)
    kept = heapq.nsmallest(cap, counts, key=lambda k: (-counts[k], _value_order(k, first[k])))
    kept.sort(key=lambda k: _value_order(k, first[k]))
    headers = [{"key": k, "label": NONE_LABEL if k == NONE else key_text(k), "n": counts[k],
                "clause": value_clause(field, k, first[k])} for k in kept]
    return headers, {k: i for i, k in enumerate(kept)}, len(counts)


def _keyed(field, rows, snapshot):
    """``(each row's key, {key: its first row's value})``."""
    key_in, value_in = key_of(field, snapshot), value_of(field, snapshot)
    keys, first = [key_in(row) for row in rows], {}
    for key, row in zip(keys, rows):
        if key not in first:
            first[key] = value_in(row)
    return keys, first


def _cell_value(spec, members, hits, goal):
    if spec.cell == "count":
        return len(members)
    if spec.cell == "share":
        return hits / len(members)
    values = sorted(v for v in (row["metrics"].get(spec.metric) for row in members)
                    if is_finite_number(v))
    return of_sorted(values, spec.agg, goal)


def _clause(row, col):
    a, b = row["clause"], col["clause"]
    return a and b and f"{a} and {b}"


def build_pivot(snapshot, rows, spec, schema):
    """The pivot payload of the filtered *rows* of *snapshot*. Raises
    ``QueryError`` on a bad ``match`` query."""
    along, across = _keyed(spec.rows, rows, snapshot), _keyed(spec.cols, rows, snapshot)
    row_heads, row_at, rows_total = _axis(spec.rows, *along, MAX_ROWS)
    col_heads, col_at, cols_total = _axis(spec.cols, *across, MAX_COLS)
    matched = None
    if spec.cell == "share":
        matched = {id(row) for row in apply_filters(rows, None, spec.match, snapshot)}
    members = {}
    for row, rk, ck in zip(rows, along[0], across[0]):
        if rk in row_at and ck in col_at:
            members.setdefault((row_at[rk], col_at[ck]), []).append(row)
    goal = metric_goal(schema, spec.metric) if spec.metric else None
    cells = [[None] * len(col_heads) for _ in row_heads]
    for (i, j), kept in members.items():
        hits = sum(id(row) in matched for row in kept) if matched is not None else None
        cell = {"n": len(kept), "value": _cell_value(spec, kept, hits, goal),
                "clause": _clause(row_heads[i], col_heads[j])}
        if hits is not None:
            cell["hits"] = hits
        cells[i][j] = cell
    return {"rows": row_heads, "cols": col_heads, "cells": cells, "total": len(rows),
            "rows_total": rows_total, "cols_total": cols_total, "cell": spec.cell,
            "match": spec.match, "metric": spec.metric, "agg": spec.agg}
