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
``has_intent`` come from them). So are its note signatures
(:mod:`vmn_exp.core.note_sigs`), for ``notes`` queries and facets. Its
``sys_*`` metrics and their summaries go to a side table too
(:mod:`vmn_exp.core.system_metrics`), which row copies, queries and chart
columns read back.

What the index keeps is compact: rows of shared keys and values
(:func:`~vmn_exp.core.index_intern.compact_row`), summaries packed once
in memory (:class:`~vmn_exp.core.metric_pack.PackedSummary`,
:func:`kept_side`), persisted as plain dicts.
"""
import json
import threading
import weakref
from collections import OrderedDict
from itertools import compress
from operator import is_not

from vmn_exp.core.fold import (
    fold_definitions,
    fold_features,
    fold_hypothesis,
    fold_intent,
    fold_row,
)
from vmn_exp.core.index_intern import compact_row, keyed
from vmn_exp.core.keyed_locks import KeyedLocks
from vmn_exp.core.metric_pack import PackedSummary
from vmn_exp.core.metric_schema import declared_fields, declared_schema
from vmn_exp.core.metric_summary import SchemaPolicies, with_schema_policies
from vmn_exp.core.note_sigs import fold_note_sigs
from vmn_exp.core.system_metrics import split_system

_SCHEMAS_KEPT = 4

# The IndexSnapshot side tables (``{verstr: value}``, empty values left out)
# that lean_row's values after the row and create note fill, in order.
SIDE_TABLES = ("metric_parts", "outputs", "declared_defs", "features", "intents", "hypotheses",
               "system_metrics", "note_sigs")
_PACKED_SIDES = ("metric_parts", "system_metrics")


def schema_key(schema):
    """A hashable, order-independent key for a metrics *schema*."""
    return json.dumps(schema or {}, sort_keys=True, default=str)


def lean_row(idx, meta, fold):
    """``(row, create note, parts, outputs, declared, features, intent,
    hypothesis, system, note sigs)`` of a folded record: the row without the schema, its
    ``metric_summary``, its ``outputs`` or its ``sys_*`` metrics; *parts*
    ``(metric_summary, run definitions)``, None when no other metric
    repeats, *outputs* None when the run stored none, *declared* the run's
    ``goal``/``hidden``/``chart`` declarations (see
    :func:`~vmn_exp.core.metric_schema.declared_fields`) or None, the run's
    folded features/intent/hypothesis or None, and *system* ``({sys metric:
    value}, their summary or None, run definitions)``, None without any,
    and *note sigs* the run's note signatures or None (see
    :func:`~vmn_exp.core.note_sigs.fold_note_sigs`, :data:`SIDE_TABLES`)."""
    row = fold_row(idx, meta, fold, with_create_note=True)
    note, summary = row.pop("create_note"), row.pop("metric_summary")
    outputs = row.pop("outputs") or None
    row["metrics"], system = split_system(row["metrics"])
    summary, system_summary = split_system(summary)
    defs = _definitions(fold) or None
    return (
        compact_row(row), note, _parts(summary, defs), outputs,
        declared_fields(defs) or None, fold_features(fold), fold_intent(fold),
        fold_hypothesis(fold), _system(system, system_summary, defs), fold_note_sigs(fold),
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
    """The run's ``goal``/``hidden``/``chart`` declarations, or None."""
    return declared_fields(_definitions(fold)) or None


def runs_declared_schema(declared_defs, row_of):
    """:func:`~vmn_exp.core.metric_schema.declared_schema` of *declared_defs*
    (``{verstr: declared}``), the runs taken oldest first by their row's
    timestamp (*row_of(verstr)*), so the latest run's declaration wins."""
    def created(verstr):
        row = row_of(verstr) or {}
        return (row.get("timestamp") or "", row.get("idx") or 0)

    return declared_schema(declared_defs[v] for v in sorted(declared_defs, key=created))


def summarized_row(row, parts, policies):
    """*row* with its metrics under *policies* (a schema's
    :class:`~vmn_exp.core.metric_summary.SchemaPolicies`); *row* itself when
    unchanged."""
    summary, defs = parts
    metrics = with_schema_policies(row["metrics"], summary, defs, policies)
    return row if metrics is row["metrics"] else dict(row, metrics=metrics)


class SchemaRows:
    """Rows summarized by a few recent schemas, kept across generations: a
    new generation summarizes only the rows the index did not reuse, and a
    row it only renumbered (a run inserted before it) keeps its summarized
    metrics. One caller per schema summarizes at a time (:meth:`turn`); a
    caller arriving meanwhile waits for it (:meth:`kept`) or gets the newest
    view kept (:meth:`latest_or`)."""

    def __init__(self):
        self._summaries = OrderedDict()  # schema key -> _Summary
        self._latest = {}  # schema key -> weakref to the view last kept
        self._lock = threading.Lock()
        self._turns = KeyedLocks("schema rows")

    def turn(self, key):
        """The schema *key*'s turn to summarize (reentrant)."""
        return self._turns.turn(key)

    def rows(self, rows, parts, schema):
        """*rows* summarized by *schema* (see :func:`summarized_row`)."""
        key = schema_key(schema)
        with self.turn(key):
            return self.rows_in_turn(key, rows, parts, schema)[0]

    def rows_in_turn(self, key, rows, parts, schema):
        """``(rows, {verstr: row})`` of :meth:`rows`, for a caller already
        holding the schema *key*'s turn. Shared: copy before changing."""
        with self._lock:
            last = self._summaries.get(key)
        if last is None or last.raw is not rows:
            last = _Summary.next(last, rows, parts, SchemaPolicies(schema))
            with self._lock:
                self._summaries[key] = last
                self._summaries.move_to_end(key)
                while len(self._summaries) > _SCHEMAS_KEPT:
                    dropped, _ = self._summaries.popitem(last=False)
                    self._latest.pop(dropped, None)
        return last.rows, last.by_verstr

    def latest_or(self, key, compute):
        """*compute()*'s view in the schema *key*'s turn, kept as the latest;
        while another thread holds that turn, the latest view still alive
        instead (waiting only when there is none)."""
        with self._turns.turn(key, blocking=False) as mine:
            if mine:
                return self.kept(key, compute)
            stale = self._latest.get(key)
            stale = stale() if stale is not None else None
            if stale is not None:
                return stale
        return self.kept(key, compute)

    def kept(self, key, compute):
        """*compute()*'s view in the schema *key*'s turn, kept as the latest
        unless a newer generation's view is."""
        with self.turn(key):
            view = compute()
        with self._lock:
            latest = self._latest.get(key)
            latest = latest() if latest is not None else None
            if key in self._summaries and (latest is None or latest.generation <= view.generation):
                self._latest[key] = weakref.ref(view)
        return view


class _Summary:
    """One schema's rows as summarized for one generation: the index's rows
    (*raw*), the summarized ones in their order and by verstr, and *memo*
    ``{verstr: (raw row, parts, summarized row)}`` (shared with the next
    generation's summary, which updates it in place)."""

    __slots__ = ("by_verstr", "memo", "raw", "rows")

    def __init__(self, raw, rows, by_verstr, memo):
        self.raw, self.rows, self.by_verstr, self.memo = raw, rows, by_verstr, memo

    @classmethod
    def next(cls, last, rows, parts, policies):
        """The summary of *rows* from *last* (or None): only the positions
        whose row object changed are summarized, at C speed found."""
        n = len(rows)
        if last is None:
            out, by_verstr, memo, gone = [None] * n, {}, {}, ()
            changed = range(n)
        else:
            raw, common = last.raw, min(n, len(last.raw))
            changed = [*compress(range(common), map(is_not, rows, raw)), *range(common, n)]
            out = [*last.rows[:common], *[None] * (n - common)]
            by_verstr, memo = last.by_verstr.copy(), last.memo
            gone = [raw[i] for i in changed if i < common] + list(raw[n:])
        for i in changed:
            out[i] = by_verstr[rows[i]["verstr"]] = _summarized(memo, rows[i], parts, policies)
        if gone:
            for verstr in {r["verstr"] for r in gone} - {rows[i]["verstr"] for i in changed}:
                memo.pop(verstr, None)
                by_verstr.pop(verstr, None)
        return cls(rows, tuple(out), by_verstr, memo)


def _summarized(memo, row, parts, policies):
    """*row* summarized under *policies*, reusing *memo*'s summary of the
    same row — or of a renumbered copy of it (same metrics, same parts)."""
    verstr = row["verstr"]
    part = parts.get(verstr)
    hit = memo.get(verstr)
    if hit is not None and hit[1] is part and hit[0]["metrics"] is row["metrics"]:
        was, _, done = hit
        if done is was:
            done = row
        elif was is not row:
            done = dict(row, metrics=done["metrics"])
    else:
        done = summarized_row(row, part, policies) if part else row
    memo[verstr] = (row, part, done)
    return done
