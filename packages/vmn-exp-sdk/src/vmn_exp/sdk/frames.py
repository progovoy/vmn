#!/usr/bin/env python3
"""Flattening reader rows into the flat, MLflow-style shape a DataFrame wants.

``mlflow.search_runs()`` and ``wandb.Api().runs`` hand back one row per run
with dotted columns; so does :func:`vmn_exp.sdk.reader.runs_dataframe`. The
flattening is plain Python (dicts in, dicts out) so it is testable and usable
without pandas; only :func:`to_dataframe` needs it, and imports it lazily —
pandas is the optional ``vmn-exp-sdk[pandas]`` extra.

``metrics.<k>`` is the row's ``metrics`` fold, the same values the query
language's ``metrics.<k>`` sees — numeric params included — so a column and a
``query=`` filter never disagree.
"""
from vmn_exp.core.status import parse_iso

PANDAS_MISSING = (
    "runs_dataframe()/get_metric_history() need pandas: "
    "pip install 'vmn-exp-sdk[pandas]'"
)

#: Scalar row fields, in column order, ahead of the dotted ones.
LEADING_COLUMNS = (
    "run_id",
    "idx",
    "name",
    "status",
    "kind",
    "parent",
    "tree_status",
    "timestamp",
    "started_at",
    "finished_at",
    "duration_sec",
    "exit_code",
    "host",
    "branch",
    "code_verstr",
    "note",
    "archived",
)
DATETIME_COLUMNS = ("timestamp", "started_at", "finished_at")
# Row dicts flattened into dotted columns, in column order.
_PREFIXES = ("metrics", "params", "tags", "inputs")
HISTORY_COLUMNS = ("step", "timestamp", "value")


def require_pandas():
    """The pandas module, or an ImportError naming the extra to install."""
    try:
        import pandas
    except ImportError as exc:
        raise ImportError(PANDAS_MISSING) from exc
    return pandas


def run_record(row):
    """One reader row as a flat ``{column: scalar}`` dict."""
    record = {"run_id": row.get("verstr")}
    for column in LEADING_COLUMNS[1:]:
        record[column] = row.get(column)
    for column in DATETIME_COLUMNS:
        record[column] = parse_iso(record[column])
    for prefix in _PREFIXES:
        for key, value in (row.get(prefix) or {}).items():
            if prefix == "inputs" and isinstance(value, dict):
                value = value.get("uri")
            record[f"{prefix}.{key}"] = value
    return record


def run_columns(records):
    """Leading columns, then every dotted column grouped by prefix and sorted."""
    seen = set()
    for record in records:
        seen.update(record)
    dotted = [
        column
        for prefix in _PREFIXES
        for column in sorted(c for c in seen if c.startswith(prefix + "."))
    ]
    return list(LEADING_COLUMNS) + dotted


def history_records(points):
    """``metric_series`` points as ``{step, timestamp, value}`` dicts."""
    return [
        {"step": p.get("step"), "timestamp": parse_iso(p.get("ts")), "value": p.get("value")}
        for p in points
    ]


def to_dataframe(records, columns):
    """A DataFrame of *records* with *columns*; date columns as UTC datetimes."""
    pd = require_pandas()
    df = pd.DataFrame.from_records(records, columns=list(columns))
    for column in DATETIME_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], utc=True)
    return df
