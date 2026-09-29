#!/usr/bin/env python3
"""Logged tables: normalized to a columnar JSON document, paged back row-major.

A document is ``{"columns": [{"name", "type"}], "data": [[column values]],
"rows": n, "truncated": bool}``. Column types are ``number``, ``string``,
``bool``, ``null`` (nothing but missing cells) or ``mixed``. Cells are made
JSON-safe: numpy scalars become Python values, NaN/inf become None, anything
else unknown is stored as its ``str``. At most :data:`MAX_TABLE_ROWS` rows are
kept.
"""
import math

MAX_TABLE_ROWS = 10_000


def _is_frame(data):
    return hasattr(data, "columns") and hasattr(data, "to_dict")


def _from_dicts(rows):
    columns = list(dict.fromkeys(k for row in rows for k in row))
    return columns, [[row.get(c) for c in columns] for row in rows]


def _from_lists(rows, columns):
    if columns is None:
        raise ValueError("A table of lists needs columns=[...]")
    rows = [list(row) for row in rows]
    bad = next((r for r in rows if len(r) != len(columns)), None)
    if bad is not None:
        raise ValueError(f"A row has {len(bad)} cells for {len(columns)} columns")
    return list(columns), rows


def _rows_of(data, columns):
    """``(column names, row-major rows)`` of a supported table input."""
    if _is_frame(data):
        split = data.to_dict(orient="split")
        return [str(c) for c in split["columns"]], [list(r) for r in split["data"]]
    if hasattr(data, "tolist") and not isinstance(data, (list, tuple)):
        data = data.tolist()  # a 2-D numpy array
    if not isinstance(data, (list, tuple)):
        raise TypeError(f"Cannot log a {type(data).__name__} as a table")
    if data and all(isinstance(row, dict) for row in data):
        names, rows = _from_dicts(data)
    else:
        names, rows = _from_lists(data, columns)
    return [str(c) for c in names], rows


def json_cell(value):
    if hasattr(value, "item") and not isinstance(value, (list, tuple, dict, str)):
        value = value.item()  # numpy scalar
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _kind(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def column_type(values):
    kinds = {_kind(v) for v in values if v is not None}
    if not kinds:
        return "null"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def table_document(data, columns=None):
    """``(document, total rows given)``: the first :data:`MAX_TABLE_ROWS` rows."""
    names, rows = _rows_of(data, columns)
    total = len(rows)
    rows = rows[:MAX_TABLE_ROWS]
    data_cols = [[json_cell(row[i]) for row in rows] for i in range(len(names))]
    return {
        "columns": [
            {"name": n, "type": column_type(col)} for n, col in zip(names, data_cols)
        ],
        "data": data_cols,
        "rows": len(rows),
        "truncated": total > len(rows),
    }, total


def _sort_key(value):
    """Numbers, then strings; bools count as numbers."""
    if isinstance(value, (bool, int, float)):
        return (0, float(value), "")
    return (1, 0.0, str(value))


def _order(column, descending):
    present = [i for i, v in enumerate(column) if v is not None]
    present.sort(key=lambda i: _sort_key(column[i]), reverse=descending)
    return present + [i for i, v in enumerate(column) if v is None]


def table_page(doc, offset=0, limit=100, sort=None, order="asc"):
    """``{"columns", "rows", "total", "offset", "truncated"}`` — a row-major page,
    optionally sorted by column *sort* (missing cells last either way)."""
    names = [c["name"] for c in doc["columns"]]
    data = doc["data"]
    total = doc["rows"]
    indexes = range(total)
    if sort is not None:
        if sort not in names:
            raise ValueError(f"No column {sort!r} in this table")
        indexes = _order(data[names.index(sort)], order == "desc")
    offset = max(int(offset), 0)
    picked = list(indexes)[offset : offset + max(int(limit), 0)]
    return {
        "columns": doc["columns"],
        "rows": [[col[i] for col in data] for i in picked],
        "total": total,
        "offset": offset,
        "truncated": bool(doc.get("truncated")),
    }
