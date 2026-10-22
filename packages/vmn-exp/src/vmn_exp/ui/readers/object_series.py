#!/usr/bin/env python3
"""A run's whole thinned series read straight from its metric objects.

Compare and outer-run charts ask many runs for a few series each. Parsing a
run's merged log for that builds one dict per metric point (and, for a
never-compacted run on S3, reads every stream segment just to rebuild the
log); here a compacted writer costs its footer and one LOD slice, and only
the JSONL logs are parsed — for their rewinds, ``define_metric`` entries and
any v1 ``metrics`` entries. The payload is the parsed log's
(:func:`~vmn_exp.ui.readers.experiment_detail.thinned_series`).
"""
from vmn_exp.core.fold import fold_definitions, fold_log
from vmn_exp.core.step_metric import join_on, step_metrics, x_lookup
from vmn_exp.ui.readers.range_series import jsonl_log, series_reader
from vmn_exp.ui.readers.series import downsample, points_per_metric


def x_of(names, x):
    """``{metric: x metric}`` for the *names* to join: *x* is a metric name
    (every other metric) or such a map; None joins nothing."""
    if x is None:
        return {}
    if isinstance(x, str):
        return {k: x for k in names if k != x}
    return {k: x[k] for k in names if k in x and x[k] != k}


def readable(storage):
    """Whether *storage* lists metric objects and per-writer JSONL logs."""
    return all(hasattr(storage, m) for m in ("metric_objects", "load_logs_by_writer"))


def object_series(storage, app_name, verstr, keys, max_points, budget=None, x=None, schema=None):
    """``(series, series_total, step_metrics)`` of a run known to exist."""
    log = jsonl_log(storage, app_name, verstr)
    reader = series_reader(storage, app_name, verstr, log)
    counts = reader.keys()
    names = list(counts) if keys is None else [k for k in keys if k in counts]
    if isinstance(x, str):
        names = [k for k in names if k != x]
    joins = x_of(names, x)
    per_metric = points_per_metric(max_points, len(names), budget)
    series = {k: reader.thinned(k, per_metric) for k in names if k not in joins}
    totals = {k: counts[k] for k in series}
    lookups = {m: x_lookup(reader.series(m)) for m in set(joins.values())}
    for k, m in joins.items():
        joined = join_on(reader.series(k), lookups[m])
        series[k], totals[k] = downsample(joined, per_metric), len(joined)
    declared = step_metrics(counts, fold_definitions(fold_log(log)), schema)
    return {k: series[k] for k in names}, {k: totals[k] for k in names}, declared
