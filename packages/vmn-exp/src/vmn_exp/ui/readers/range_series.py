#!/usr/bin/env python3
"""Series of a step range and paged metric keys, read straight from a run's
metric objects (plan 12 §7).

A chart zoom asks for ``step_min..step_max`` at full resolution. Unlike the
polled detail (:mod:`~vmn_exp.ui.readers.parsed_logs`, which parses every
point once and keeps it), these go through :class:`SeriesReader`, so a
compacted writer costs its footer, one LOD slice and the raw chunks at the
range's edges. The JSONL logs are read for their rewinds, ``define_metric``
entries and any v1 ``metrics`` entries.
"""
from vmn_exp.core.fold import fold_definitions, fold_log
from vmn_exp.core.metric_entries import is_metric_entry
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.core.step_metric import step_metrics
from vmn_exp.storage.files import flatten_logs
from vmn_exp.ui.readers.series import points_per_metric


def _jsonl_log(storage, app_name, verstr):
    load = getattr(storage, "load_logs_by_writer", None)
    return flatten_logs(load(app_name, verstr) if load else {})


def _reader(storage, app_name, verstr, log):
    legacy = [e for e in log if is_metric_entry(e)]
    return SeriesReader.from_storage(storage, app_name, verstr, log=log, legacy=legacy)


def range_series(storage, app_name, verstr, keys, max_points, budget, step_range, schema=None):
    """``(series, series_total, step_metrics)`` of *keys* (None: all) within
    *step_range* (``(lo, hi)``, either may be None), or None when the run is
    gone. ``series_total`` counts each metric's whole series."""
    if storage.load_metadata(app_name, verstr) is None:
        return None
    log = _jsonl_log(storage, app_name, verstr)
    reader = _reader(storage, app_name, verstr, log)
    counts = reader.keys()
    names = sorted(counts) if keys is None else [k for k in keys if k in counts]
    per_metric = points_per_metric(max_points, len(names), budget)
    series = {k: reader.thinned(k, per_metric, step_range) for k in names}
    declared = step_metrics(counts, fold_definitions(fold_log(log)), schema)
    return series, {k: counts[k] for k in names}, declared


def metric_keys(storage, app_name, verstr, prefix="", offset=0, limit=None):
    """``{"keys": [{"name", "count"}], "total", "offset", "limit"}`` — the
    run's metric names starting with *prefix*, name-ordered, one page of
    them; None when the run is gone."""
    if storage.load_metadata(app_name, verstr) is None:
        return None
    reader = _reader(storage, app_name, verstr, _jsonl_log(storage, app_name, verstr))
    counts = reader.keys()
    names = sorted(k for k in counts if k.startswith(prefix or ""))
    page = names[offset:] if limit is None else names[offset : offset + limit]
    return {
        "keys": [{"name": k, "count": counts[k]} for k in page],
        "total": len(names),
        "offset": offset,
        "limit": limit,
    }
