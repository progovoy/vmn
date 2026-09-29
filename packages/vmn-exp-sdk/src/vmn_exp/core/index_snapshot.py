#!/usr/bin/env python3
"""An immutable view of an :class:`~version_stamp.core.experiment_index.ExperimentIndex`
at one generation.

The index builds one per generation and swaps it in whole, so a reader holds a
consistent set of rows, run states and parent edges without taking the index
lock or touching storage. Rows are shared between readers: treat them (and the
dicts here) as read-only and copy before changing anything.

A snapshot's rows follow no metrics schema; :meth:`IndexSnapshot.summarized`
is the view a schema gives (see :mod:`vmn_exp.core.index_views`).
"""
from dataclasses import dataclass, field, replace

from vmn_exp.core.index_views import SchemaRows, lean_row, schema_key
from vmn_exp.core.status import observed_at_from_mtime

_VIEWS_PER_SNAPSHOT = 4


@dataclass(frozen=True, eq=False)
class IndexSnapshot:
    app_name: str
    generation: int
    rows: tuple  # experiment_row dicts in storage order, idx set
    run_states: dict  # {verstr: raw run state or None}
    edges: dict  # {verstr: parent verstr or None}
    create_notes: dict = field(default_factory=dict, repr=False)
    # {verstr: when the store last saw run_state.yml written (aware UTC
    # datetime), or None} — pass it to derive_status/status_fields as
    # observed_at for clock-skew-proof stuck detection.
    run_state_observed_at: dict = field(default_factory=dict, repr=False)
    # {verstr: (metric_summary, run definitions)} of rows with a repeated
    # metric — what a schema view and a row copy's metric_summary read.
    metric_parts: dict = field(default_factory=dict, repr=False)
    _by_verstr: dict = field(default_factory=dict, repr=False)
    _schema_rows: SchemaRows = field(default_factory=SchemaRows, repr=False)
    _views: dict = field(default_factory=dict, repr=False)  # schema key -> view
    _base: object = field(default=None, repr=False)  # a view's schema-less snapshot

    @classmethod
    def build(
        cls, app_name, generation, rows, run_states, create_notes=None, observed_at=None,
        metric_parts=None,
    ):
        rows = tuple(rows)
        return cls(
            app_name=app_name,
            generation=generation,
            rows=rows,
            run_states=run_states,
            edges={row["verstr"]: row.get("parent") for row in rows},
            create_notes=create_notes or {},
            run_state_observed_at=observed_at or {},
            metric_parts=metric_parts or {},
            _by_verstr={row["verstr"]: row for row in rows},
        )

    def row(self, verstr):
        """The row of *verstr*, or None."""
        return self._by_verstr.get(verstr)

    def metric_summary(self, verstr):
        """``{metric: {"last", "min", "max"}}`` of *verstr*'s repeated metrics."""
        parts = self.metric_parts.get(verstr)
        return dict(parts[0]) if parts else {}

    def summarized(self, schema):
        """This snapshot with its rows' metrics under the metrics *schema* —
        the same object for the same schema, and this very snapshot when the
        schema changes no row. The shared rows are never touched."""
        base = self._base or self
        if not schema or not base.metric_parts:
            return base
        key = schema_key(schema)
        view = base._views.get(key)
        if view is None:
            view = base._view(base._schema_rows.rows(base.rows, base.metric_parts, schema))
            if len(base._views) >= _VIEWS_PER_SNAPSHOT:
                base._views.clear()
            base._views[key] = view
        return view

    def _view(self, rows):
        if all(a is b for a, b in zip(rows, self.rows)):
            return self
        return replace(
            self, rows=tuple(rows), _by_verstr={r["verstr"]: r for r in rows},
            _views={}, _base=self,
        )

    def resolve(self, ref, latest=False, kind="experiment"):
        """``(verstr, error)`` for *ref*, like the CLI's ``_resolve_verstr``.

        Accepts ``latest``/``@latest`` (or *latest*), ``@N`` (the storage
        index), an exact verstr, a unique dev-verstr prefix, or a stamped
        (non-dev) version passed through untouched.
        """
        if latest or ref in ("latest", "@latest"):
            return self._latest(kind)
        if ref is None:
            return None, None
        if ref.startswith("@"):
            return self._at_index(ref)
        if ref in self._by_verstr or "-dev." not in ref:
            return ref, None
        return self._by_prefix(ref, kind)

    def _latest(self, kind):
        if not self.rows:
            return None, f"No {kind}s found for {self.app_name}"
        newest = max(self.rows, key=lambda r: r.get("timestamp") or "")
        return newest["verstr"], None

    def _at_index(self, ref):
        idx = ref[1:]
        if not idx.isdigit():
            return None, f"Invalid index reference '{ref}' (use @N, e.g. @1)"
        n = int(idx)
        if n < 1 or n > len(self.rows):
            return None, f"Index '{ref}' out of range (1..{len(self.rows)})"
        return self.rows[n - 1]["verstr"], None

    def _by_prefix(self, ref, kind):
        matches = sorted(v for v in self._by_verstr if v.startswith(ref))
        if len(matches) == 1:
            return matches[0], None
        if matches:
            return None, (
                f"Ambiguous prefix '{ref}': matches {len(matches)} {kind}s: "
                + ", ".join(matches)
            )
        return None, f"{kind.capitalize()} '{ref}' not found"


class RowCache:
    """Materialized snapshot parts shared by successive snapshots.

    A row is re-folded only when its record changed and re-numbered (a
    shallow copy) when it moved, so a heartbeat-only generation reuses every
    row object. The per-verstr maps a snapshot carries are patched for the
    keys that changed and copied (C-level) into each snapshot, so while the
    order only grows at its end a generation costs O(changed) — at 100k
    records re-deriving every row's maps took ~0.4s per generation. Any other
    reorder rebuilds them from the cached rows.
    """

    def __init__(self):
        self._rows = {}  # key -> (row with idx, create note, metric parts)
        self._observed = {}  # key -> (rs_sig, store write time it encodes)
        self._order = []  # the keys of the last snapshot, in order
        self._pos = {}  # key -> its position in _order
        self._list = []  # their rows
        self._maps = _Maps()
        self._schema_rows = SchemaRows()  # shared by its snapshots' views

    def pop(self, key, default=None):
        return self._rows.pop(key, default)

    def _row(self, key, idx, record):
        cached = self._rows.get(key)
        if cached is None:
            cached = self._rows[key] = lean_row(idx, record["meta"], record["fold"])
        elif cached[0]["idx"] != idx:
            cached = self._rows[key] = (dict(cached[0], idx=idx),) + cached[1:]
        return cached

    def _observed_of(self, key, rs_sig):
        cached = self._observed.get(key)
        if cached is None or cached[0] != rs_sig:
            cached = self._observed[key] = (rs_sig, _observed_at(rs_sig))
        return cached[1]

    def snapshot(self, app_name, generation, order, records, touched=None):
        """The :class:`IndexSnapshot` of *records* (``{key: record}``) in
        *order*. *touched*: the keys whose record changed since the last
        call; None (unknown) rebuilds every map."""
        grown = touched is not None and order[: len(self._order)] == self._order
        if not (grown and self._patch(touched, records)):
            self._rebuild(order, records)
        for key in order[len(self._list):]:
            self._put(key, len(self._list), records[key])
        self._order = list(order)
        m = self._maps
        return IndexSnapshot(
            app_name=app_name, generation=generation, rows=tuple(self._list),
            run_states=dict(m.states), edges=dict(m.edges), create_notes=dict(m.notes),
            run_state_observed_at=dict(m.observed), metric_parts=dict(m.parts),
            _by_verstr=dict(m.rows), _schema_rows=self._schema_rows,
        )

    def _patch(self, touched, records):
        """Swap in the touched rows already in the order; False when one of
        them no longer maps to the same verstr (a rebuild is due)."""
        for key in touched:
            pos = self._pos.get(key)
            if pos is None:
                continue  # new: appended after
            if records[key]["meta"]["verstr"] != self._list[pos]["verstr"]:
                return False
            self._put(key, pos, records[key])
        return True

    def _rebuild(self, order, records):
        self._pos, self._list, self._maps = {}, [], _Maps()
        live = set(order)
        self._observed = {k: v for k, v in self._observed.items() if k in live}
        for pos, key in enumerate(order):
            self._put(key, pos, records[key])

    def _put(self, key, pos, record):
        row, note, parts = self._row(key, pos + 1, record)
        if pos == len(self._list):
            self._list.append(row)
        else:
            self._list[pos] = row
        self._pos[key] = pos
        observed = self._observed_of(key, record["rs_sig"])
        self._maps.put(row, note, parts, record["run_state"], observed)


class _Maps:
    """What a snapshot keys by verstr, kept current between snapshots."""

    def __init__(self):
        self.rows, self.notes, self.states, self.observed, self.edges = {}, {}, {}, {}, {}
        self.parts = {}

    def put(self, row, note, parts, state, observed):
        verstr = row["verstr"]
        self.rows[verstr] = row
        self.notes[verstr] = note
        if parts:
            self.parts[verstr] = parts
        else:
            self.parts.pop(verstr, None)
        self.states[verstr] = state
        self.observed[verstr] = observed
        self.edges[verstr] = row.get("parent")


def _observed_at(rs_sig):
    """The run state's storage mtime from its ``[size, mtime, ...]`` signature."""
    return observed_at_from_mtime(rs_sig[1]) if rs_sig and len(rs_sig) > 1 else None
