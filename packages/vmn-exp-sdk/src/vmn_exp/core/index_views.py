#!/usr/bin/env python3
"""Index rows as a metrics schema summarizes them — per read, not per index.

An index row is folded once, summarized by the run's own ``define_metric``
policies only. A caller's metrics schema (conf.yml ``experiment.metrics``)
can then only change the value of a metric logged more than once, so each row
keeps just what that needs beside it — its ``metric_summary`` and the run's
definitions, its *parts* — and :class:`SchemaRows` derives a schema's rows
from them, reusing every row the index did not re-derive since.

``metric_summary`` itself stays off the shared rows (a leaderboard at 100k
runs would carry it in every payload); the row copies the reader API and the
CLI hand out put it back. So do ``outputs`` — a run logging an image per step
has one per step — which the snapshot keeps per verstr for the lineage index
and ``outputs.*`` queries (:func:`~vmn_exp.core.query.filter_rows` ``extra``).
"""
import json
import threading
from collections import OrderedDict

from vmn_exp.core.fold import fold_definitions, fold_row
from vmn_exp.core.metric_summary import with_policies

_SCHEMAS_KEPT = 4


def schema_key(schema):
    """A hashable, order-independent key for a metrics *schema*."""
    return json.dumps(schema or {}, sort_keys=True, default=str)


def lean_row(idx, meta, fold):
    """``(row, create note, parts, outputs)`` of a folded record: the row
    without the schema, its ``metric_summary`` or its ``outputs``; *parts*
    None when no metric repeats, *outputs* None when the run stored none."""
    row = fold_row(idx, meta, fold, with_create_note=True)
    note, summary = row.pop("create_note"), row.pop("metric_summary")
    parts = (summary, fold_definitions(fold) or None) if summary else None
    return row, note, parts, row.pop("outputs") or None


def summarized_row(row, parts, schema):
    """*row* with its metrics under *schema*; *row* itself when unchanged."""
    summary, defs = parts
    metrics = with_policies(row["metrics"], summary, defs, schema)
    return row if metrics is row["metrics"] else dict(row, metrics=metrics)


class SchemaRows:
    """Rows summarized by a few recent schemas, kept across generations: a
    row object the index reused keeps its summarized row."""

    def __init__(self):
        self._memos = OrderedDict()  # schema key -> {verstr: (row, summarized)}
        self._lock = threading.Lock()

    def rows(self, rows, parts, schema):
        """*rows* summarized by *schema* (see :func:`summarized_row`)."""
        key = schema_key(schema)
        with self._lock:
            memo = self._memos.pop(key, {})
        fresh, out = {}, []
        for row in rows:
            verstr = row["verstr"]
            hit = memo.get(verstr)
            if hit is None or hit[0] is not row:
                part = parts.get(verstr)
                hit = (row, summarized_row(row, part, schema) if part else row)
            fresh[verstr] = hit
            out.append(hit[1])
        with self._lock:
            self._memos[key] = fresh
            while len(self._memos) > _SCHEMAS_KEPT:
                self._memos.popitem(last=False)
        return out
