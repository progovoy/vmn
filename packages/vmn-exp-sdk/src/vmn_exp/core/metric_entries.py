#!/usr/bin/env python3
"""Between ``metrics`` log entries and metric streams (plan 12 §4.1, §5.5).

Writers still build ``{"type": "metrics", "values", "step", "timestamp"}``
entries (sanitized by :mod:`vmn_exp.core.values`); :func:`record_metric_entries`
turns them into points of a :class:`~vmn_exp.core.metric_stream.MetricWriter`
instead of JSONL lines. :func:`points_to_entries` goes the other way for
display — points of one ``(step, ts)`` become one entry again, so log views
read as they always did. Pure: no storage.
"""
import time

from vmn_exp.core.metric_time import iso_to_us, us_to_iso

METRICS = "metrics"


def is_metric_entry(entry):
    return isinstance(entry, dict) and entry.get("type") == METRICS


def split_metric_entries(entries):
    """``(metric entries, the others)`` of *entries*, each in order."""
    metrics = [e for e in entries if is_metric_entry(e)]
    return metrics, [e for e in entries if not is_metric_entry(e)]


def add_metric_entry(writer, entry):
    """Buffer *entry*'s values as points of *writer*, all at its timestamp
    (now, for an entry without one)."""
    ts_us = iso_to_us(entry.get("timestamp"))
    if ts_us is None:
        ts_us = int(time.time() * 1_000_000)
    step = entry.get("step")
    step = None if isinstance(step, bool) or not isinstance(step, (int, float)) else step
    for key, value in (entry.get("values") or {}).items():
        writer.add(key, value, step=step, ts_us=ts_us)


def record_metric_entries(writer, entries, inherited=False):
    """Append *entries* to *writer*'s stream as one block; True on success."""
    for entry in entries:
        add_metric_entry(writer, entry)
    return writer.flush(inherited=inherited)


def points_to_entries(points, inherited=False):
    """``metrics`` entries of ``(ts_us, step, key, value)`` *points* (in
    series order): one per ``(step, ts)``, keys in first-logged order."""
    grouped = {}
    for ts_us, step, key, value in points:
        entry = grouped.get((ts_us, step))
        if entry is None:
            entry = grouped[(ts_us, step)] = {"timestamp": us_to_iso(ts_us), "type": METRICS,
                                              "values": {}}
            if step is not None:
                entry["step"] = step
            if inherited:
                entry["inherited"] = True
        entry["values"][key] = value
    return sorted(grouped.values(), key=lambda e: iso_to_us(e["timestamp"]))
