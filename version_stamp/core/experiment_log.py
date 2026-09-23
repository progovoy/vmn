#!/usr/bin/env python3
"""Folding an experiment log into the numbers every reader shows.

An experiment log is an append-only list of entries (``create``, ``params``,
``metrics``, ``note``, ...). Everything that turns such a list into a row — the
latest value of each metric, the per-metric series, the effective params, the
leaderboard row itself — lives here, so the CLI (``vmn exp``), the ui readers
and the ``version_stamp.exp`` SDK all agree by construction instead of by
copy-paste.

Pure functions over plain data, plus the two reads that only need a duck-typed
storage backend (:func:`load_log`, :func:`list_artifacts`). No clock, no vcs, no
CLI arguments — and, like the rest of ``core``, no imports from ``cli``, ``ui``
or ``exp``.
"""
import math
import os

from version_stamp.core.logging import VMN_LOGGER

# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------


def entry_params(entry):
    """Params carried by a log entry.

    `create` records params up front, `run.log_params()` mid-run.
    """
    if entry.get("type") in ("create", "params"):
        return entry.get("params") or {}
    return {}


def effective_params(log):
    """Effective params: the `create` entry's, folded with later `params` ones."""
    params = {}
    for entry in log:
        params.update(entry_params(entry))
    return params


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _foldable_param(value):
    """A param as a metric value: a finite number (bools fold as 1.0/0.0) — else None.

    ``missing=nan`` (xgboost's default) is a setting, not a measurement;
    folding it in made every such run carry a NaN "metric".
    """
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def latest_metrics(log):
    """Scan log entries and return the latest value for each metric."""
    metrics = {}
    for entry in log:
        if entry.get("type") == "metrics" and "values" in entry:
            metrics.update(entry["values"])
        else:
            for k, v in entry_params(entry).items():
                number = _foldable_param(v)
                if number is not None:
                    metrics[k] = number
    return metrics


def metric_series(log):
    """Fold a log into per-metric point lists for charting.

    Returns ``{metric: [{"step": N|None, "ts": iso, "value": v}, ...]}`` in
    log order.
    """
    series = {}
    for entry in log:
        if entry.get("type") != "metrics":
            continue
        step = entry.get("step")
        ts = entry.get("timestamp")
        for key, value in (entry.get("values") or {}).items():
            series.setdefault(key, []).append({"step": step, "ts": ts, "value": value})
    return series


def last_metric_at(log):
    """Timestamp of the newest ``metrics`` entry (the log is time-ordered)."""
    for entry in reversed(log):
        if entry.get("type") == "metrics":
            return entry.get("timestamp")
    return None


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


def experiment_row(idx, meta, log):
    """One leaderboard row: an experiment's metadata, params and folded metrics.

    *idx* is the 1-based storage index — what ``vmn exp show <app> -v @N``
    resolves — and is assigned before any sort so it sticks to the row.

    ``params`` carries every param verbatim; ``metrics`` stays numeric-only (with
    the numeric params folded in), because sorting and charting depend on that.
    """
    return {
        "idx": idx,
        "verstr": meta["verstr"],
        "code_verstr": meta.get("code_verstr", meta["verstr"]),
        "timestamp": meta.get("timestamp"),
        "note": meta.get("note"),
        "branch": meta.get("branch"),
        "base_version": meta.get("base_version"),
        "user_meta": meta.get("user_meta"),
        "params": effective_params(log),
        "metrics": latest_metrics(log),
        "parent": meta.get("parent"),
        "last_metric_at": last_metric_at(log),
    }


def filter_by_status(rows, status=None):
    """Keep rows whose status is in *status* — a list or a comma-separated string."""
    if not status:
        return rows
    names = status.split(",") if isinstance(status, str) else status
    wanted = {s.strip() for s in names}
    return [r for r in rows if r["status"] in wanted]


def primary_metric(schema):
    """The metric the schema marks ``primary: true``, or None."""
    return next((k for k, v in (schema or {}).items() if v.get("primary")), None)


def sort_by_metric(rows, schema, sort=None):
    """Order rows like ``vmn exp list``: by *sort*, else by the primary metric.

    A metric's direction comes from its own schema entry; a metric absent from
    the schema sorts ascending. Rows whose value is missing, None, non-finite or
    non-numeric sort last in either direction, in their original order. Rows
    are returned unchanged when the metric is not present anywhere.
    """
    keys = set()
    for row in rows:
        keys.update(row["metrics"])

    metric = sort or primary_metric(schema)
    if not metric or metric not in keys:
        return rows

    descending = metric in (schema or {}) and metric_sort_descending(schema, metric)
    ranked = [r for r in rows if _sortable(r["metrics"].get(metric))]
    unranked = [r for r in rows if not _sortable(r["metrics"].get(metric))]
    ranked.sort(key=lambda r: r["metrics"][metric], reverse=descending)
    return ranked + unranked


def _sortable(value):
    """Whether *value* can take a place in a metric ranking (NaN cannot)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


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
