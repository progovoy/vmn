#!/usr/bin/env python3
"""Folding an experiment log into the numbers every reader shows.

An experiment log is an append-only list of entries (``create``, ``params``,
``metrics``, ``note``, ...). Everything that turns such a list into a row — the
latest value of each metric, the per-metric series, the effective params, the
leaderboard row itself — lives here, so the CLI (``vmn-exp``), the ui readers
and the ``vmn_exp.sdk`` SDK all agree by construction instead of by
copy-paste.

Pure functions over plain data, plus the two reads that only need a duck-typed
storage backend (:func:`load_log`, :func:`list_artifacts`). No clock, no vcs, no
CLI arguments — and, like the rest of ``core``, no imports from ``cli``, ``ui``
or ``exp``.
"""
import os

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.rewind import drop_rewound
from vmn_exp.core.values import is_finite_number
from vmn_exp.core.fold import (  # noqa: F401  (re-exported)
    _foldable_param,
    entry_params,
    fold_last_metric_at,
    fold_log,
    fold_metrics,
    fold_row,
    fold_values,
)

# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------


def effective_params(log):
    """Effective params: the `create` entry's, folded with later `params` ones."""
    return fold_values(fold_log(log), "params")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def latest_metrics(log):
    """The latest value of each metric, numeric params folded in (see :func:`fold_log`)."""
    return fold_values(fold_log(log), "metrics")


def summary_metrics(log, schema=None):
    """Each metric's value under its summary policy — what rows rank on
    (see :mod:`vmn_exp.core.metric_summary`)."""
    return fold_metrics(fold_log(log), schema)[0]


def metric_series(log):
    """Fold a log into per-metric point lists for charting.

    Returns ``{metric: [{"step": N|None, "ts": iso, "value": v}, ...]}`` in
    log order (join them on an x metric with
    :func:`~vmn_exp.core.step_metric.join_all`).
    """
    series = {}
    for entry in drop_rewound(log):
        if entry.get("type") != "metrics":
            continue
        step = entry.get("step")
        ts = entry.get("timestamp")
        for key, value in (entry.get("values") or {}).items():
            series.setdefault(key, []).append({"step": step, "ts": ts, "value": value})
    return series


def last_metric_at(log):
    """Timestamp of the newest ``metrics`` entry (the log is time-ordered)."""
    return fold_last_metric_at(fold_log(log))


def metric_sort_descending(schema, key):
    """Whether metric ``key`` sorts best-first as descending (higher is better).

    Driven by ``goal: min|max`` in the metrics schema (``max`` = higher-is-better
    = descending). Unspecified metrics default to higher-is-better.
    """
    entry = (schema or {}).get(key, {}) or {}
    goal = entry.get("goal")
    if goal is None:
        return True
    if goal not in ("min", "max"):
        VMN_LOGGER.warning(f"Invalid goal '{goal}' for metric '{key}'; using 'max'")
        goal = "max"
    return goal == "max"


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def experiment_row(idx, meta, log, schema=None):
    """One leaderboard row: an experiment's metadata, params and folded metrics.

    The fold rules live in :mod:`vmn_exp.core.fold`, which the
    experiment index folds incrementally with — so both agree by construction.
    *schema* (the app's metrics schema) sets metrics' summary policies.
    """
    return fold_row(idx, meta, fold_log(log), schema=schema)


def filter_by_status(rows, status=None):
    """Keep rows whose status is in *status* — a list or a comma-separated string."""
    if not status:
        return rows
    names = status.split(",") if isinstance(status, str) else status
    wanted = {s.strip() for s in names}
    return [r for r in rows if r["status"] in wanted]


def filter_archived(rows, include_archived=False):
    """Hide archived rows unless *include_archived* — what every listing does."""
    if include_archived:
        return rows
    return [r for r in rows if not r.get("archived")]


def primary_metric(schema):
    """The metric the schema marks ``primary: true``, or None."""
    return next((k for k, v in (schema or {}).items() if v.get("primary")), None)


TIMESTAMP_SORT = "timestamp"
IDX_SORT = "idx"
# Row fields that sort chronologically, like ``timestamp``: the run's own
# start and end, from its run_state.
DATE_SORTS = (TIMESTAMP_SORT, "started_at", "finished_at")


def sort_by_metric(rows, schema, sort=None, descending=None):
    """Order rows like ``vmn-exp list``: by *sort*, else by the primary metric.

    A metric's direction comes from its own schema entry; a metric absent from
    the schema sorts ascending. *descending* forces the direction. Rows whose
    value is missing, None, non-finite or non-numeric sort last in either
    direction, in their original order. ``sort="timestamp"`` orders by creation
    time, ``started_at``/``finished_at`` by the run's start/end (undated rows
    last) and ``sort="idx"`` by run number,
    newest first unless *descending* is False. When the metric is not
    present anywhere, rows keep storage order (reversed if *descending*).
    """
    if sort in DATE_SORTS:
        return _by_date(rows, sort, newest_first=descending is not False)
    if sort == IDX_SORT:
        return sorted(rows, key=lambda r: r["idx"], reverse=descending is not False)

    keys = set()
    for row in rows:
        keys.update(row["metrics"])

    metric = sort or primary_metric(schema)
    if not metric or metric not in keys:
        return rows[::-1] if descending else rows

    if descending is None:
        descending = metric in (schema or {}) and metric_sort_descending(schema, metric)
    ranked = [r for r in rows if is_finite_number(r["metrics"].get(metric))]
    unranked = [r for r in rows if not is_finite_number(r["metrics"].get(metric))]
    ranked.sort(key=lambda r: r["metrics"][metric], reverse=descending)
    return ranked + unranked


def _by_date(rows, field, newest_first):
    """Chronological order on *field*; rows without it go last either way."""
    stamped = [r for r in rows if r.get(field)]
    stamped.sort(key=lambda r: r[field], reverse=newest_first)
    return stamped + [r for r in rows if not r.get(field)]


# ---------------------------------------------------------------------------
# Storage-backed reads (duck-typed backend: local checkout, S3, ...)
# ---------------------------------------------------------------------------


def load_log(storage, app_name, verstr):
    """Load experiment log from storage, merging per-writer JSONL files."""
    return storage.load_merged_log(app_name, verstr)


def list_artifacts(storage, app_name, verstr):
    """``[{"name", "size"}]`` for an experiment's artifact files, name-ordered.

    The backend answers, so S3 records list theirs too; a duck-typed storage
    without ``list_artifacts`` falls back to its local artifacts directory.
    """
    if hasattr(storage, "list_artifacts"):
        return storage.list_artifacts(app_name, verstr)
    art_dir = storage.list_artifact_files(app_name, verstr)
    if not art_dir or not os.path.isdir(art_dir):
        return []
    return [
        {"name": name, "size": os.path.getsize(os.path.join(art_dir, name))}
        for name in sorted(os.listdir(art_dir))
        if os.path.isfile(os.path.join(art_dir, name))
    ]
