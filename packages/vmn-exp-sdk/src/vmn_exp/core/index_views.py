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
A run's ``features``, ``intent`` and hypothesis are kept the same way, for
similarity; row copies leave them out (only the row's ``author`` and
``has_intent`` come from them). Its ``sys_*`` metrics and their summaries go
to a side table too (:mod:`vmn_exp.core.system_metrics`), which row copies,
queries and chart columns read back.

What the index keeps is compact: rows of shared keys and values
(:func:`~vmn_exp.core.index_intern.compact_row`), summaries packed once
in memory (:class:`~vmn_exp.core.metric_pack.PackedSummary`,
:func:`kept_side`), persisted as plain dicts.
"""
import json
import threading
from collections import OrderedDict

from vmn_exp.core.fold import (
    fold_definitions,
    fold_features,
    fold_hypothesis,
    fold_intent,
    fold_row,
)
from vmn_exp.core.index_intern import compact_row, keyed
from vmn_exp.core.metric_pack import PackedSummary
from vmn_exp.core.metric_schema import declared_fields, declared_schema
from vmn_exp.core.metric_summary import with_policies
from vmn_exp.core.system_metrics import split_system

_SCHEMAS_KEPT = 4

# The IndexSnapshot side tables (``{verstr: value}``, empty values left out)
# that lean_row's values after the row and create note fill, in order.
SIDE_TABLES = ("metric_parts", "outputs", "declared_defs", "features", "intents", "hypotheses",
               "system_metrics")
_PACKED_SIDES = ("metric_parts", "system_metrics")


def schema_key(schema):
    """A hashable, order-independent key for a metrics *schema*."""
    return json.dumps(schema or {}, sort_keys=True, default=str)


def lean_row(idx, meta, fold):
    """``(row, create note, parts, outputs, declared, features, intent,
    hypothesis, system)`` of a folded record: the row without the schema, its
    ``metric_summary``, its ``outputs`` or its ``sys_*`` metrics; *parts*
    ``(metric_summary, run definitions)``, None when no other metric
    repeats, *outputs* None when the run stored none, *declared* the run's
    ``goal``/``hidden`` declarations (see
    :func:`~vmn_exp.core.metric_schema.declared_fields`) or None, the run's
    folded features/intent/hypothesis or None, and *system* ``({sys metric:
    value}, their summary or None, run definitions)``, None without any
    (see :data:`SIDE_TABLES`)."""
    row = fold_row(idx, meta, fold, with_create_note=True)
    note, summary = row.pop("create_note"), row.pop("metric_summary")
    outputs = row.pop("outputs") or None
    row["metrics"], system = split_system(row["metrics"])
    summary, system_summary = split_system(summary)
    defs = _definitions(fold) or None
    return (
        compact_row(row), note, _parts(summary, defs), outputs,
        declared_fields(defs) or None, fold_features(fold), fold_intent(fold),
        fold_hypothesis(fold), _system(system, system_summary, defs),
    )


def _parts(summary, defs):
    return (summary, defs) if summary else None


def _system(values, summary, defs):
    return (keyed(values), summary or None, defs) if values else None


def kept_side(kind, value):
    """The side table *kind*'s *value* (a :func:`lean_row` one, or as
    JSON-decoded) as a snapshot keeps it: its summary packed, a decoded
    one's sys metric names shared; *value* itself when it already is."""
    if kind not in _PACKED_SIDES or not value:
        return value
    *values, summary, defs = value  # ([values,] summary, run definitions)
    packed = PackedSummary.of(summary)
    if packed is summary and isinstance(value, tuple):
        return value
    if values and isinstance(value, list):
        values = [keyed(values[0])]
    return (*values, packed, defs)


def kept_lean(lean):
    """A :func:`lean_row` tuple as a snapshot keeps it (see :func:`kept_side`)."""
    row, note, *values = lean
    return (row, note, *(kept_side(k, v) for k, v in zip(SIDE_TABLES, values)))


def _definitions(fold):
    return fold_definitions(fold) if fold.get("metric_defs") else {}


def run_declared(fold):
    """The run's ``goal``/``hidden`` declarations, or None."""
    return declared_fields(_definitions(fold)) or None


def runs_declared_schema(declared_defs, row_of):
    """:func:`~vmn_exp.core.metric_schema.declared_schema` of *declared_defs*
    (``{verstr: declared}``), the runs taken oldest first by their row's
    timestamp (*row_of(verstr)*), so the latest run's declaration wins."""
    def created(verstr):
        row = row_of(verstr) or {}
        return (row.get("timestamp") or "", row.get("idx") or 0)

    return declared_schema(declared_defs[v] for v in sorted(declared_defs, key=created))


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
