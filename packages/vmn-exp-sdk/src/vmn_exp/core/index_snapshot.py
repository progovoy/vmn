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
import weakref
from dataclasses import dataclass, field, replace

from vmn_exp.core.index_snapshot_maps import SnapshotMaps
from vmn_exp.core.index_views import (
    SIDE_TABLES,
    SchemaRows,
    kept_lean,
    kept_side,
    lean_row,
    runs_declared_schema,
    schema_key,
)
from vmn_exp.core.resolve_ref import RefLookups, no_runs_error, resolve_with
from vmn_exp.core.status import derive_status, observed_at_from_mtime
from vmn_exp.core.tree import children_by_parent

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
    # {verstr: {path: {path, digest, size}}} of rows with outputs — off the
    # rows, which list pages serve (see outputs_of).
    outputs: dict = field(default_factory=dict, repr=False)
    # {verstr: {metric: {"goal"?, "hidden"?, "chart"?}}} of rows whose run declares
    # any — what declared_schema() merges.
    declared_defs: dict = field(default_factory=dict, repr=False)
    # {verstr: value} of rows with a folded features entry / intent /
    # hypothesis (see vmn_exp.core.fold_facts) — off the rows like outputs.
    features: dict = field(default_factory=dict, repr=False)
    intents: dict = field(default_factory=dict, repr=False)
    hypotheses: dict = field(default_factory=dict, repr=False)
    # {verstr: ({sys metric: value}, packed summary or None, run definitions)}
    # of rows with sys_* metrics, which their rows leave out (see metrics_of).
    system_metrics: dict = field(default_factory=dict, repr=False)
    # {verstr: {sig: {count, last_at}}} of rows whose run logged notes (see
    # vmn_exp.core.note_sigs) — off the rows like intents.
    note_sigs: dict = field(default_factory=dict, repr=False)
    # (rows loaded, rows expected) while a remote store's load is published
    # chunk by chunk; None once every record was read.
    loading: tuple = None
    _declared: list = field(default_factory=list, repr=False)  # memo, shared by views
    _children: list = field(default_factory=list, repr=False)  # children_of memo, ditto
    _up: list = field(default_factory=list, repr=False)  # ancestor fields (core/query_up.py), ditto
    _by_verstr: dict = field(default_factory=dict, repr=False)
    _schema_rows: SchemaRows = field(default_factory=SchemaRows, repr=False)
    _views: dict = field(default_factory=dict, repr=False)  # schema key -> view
    # A view's schema-less snapshot, held weakly (that one holds the view in
    # _views: a cycle outlives its generation once frozen, see gc_pause), and
    # its rows, to summarize again once nothing else holds that snapshot.
    _base: object = field(default=None, repr=False)
    _raw_rows: tuple = field(default=None, repr=False)

    @classmethod
    def build(
        cls, app_name, generation, rows, run_states, create_notes=None, observed_at=None,
        metric_parts=None, outputs=None, declared_defs=None,
        features=None, intents=None, hypotheses=None, system_metrics=None, note_sigs=None,
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
            outputs=outputs or {},
            declared_defs=declared_defs or {},
            features=features or {},
            intents=intents or {},
            hypotheses=hypotheses or {},
            system_metrics=system_metrics or {},
            note_sigs=note_sigs or {},
            _by_verstr={row["verstr"]: row for row in rows},
        )

    def row(self, verstr):
        """The row of *verstr*, or None."""
        return self._by_verstr.get(verstr)

    def metric_summary(self, verstr):
        """``{metric: {"last", "min", "max", "first", "mean"}}`` of
        *verstr*'s repeated metrics, its ``sys_*`` ones included."""
        parts, system = self.metric_parts.get(verstr), self.system_metrics.get(verstr)
        summary = parts[0].to_dict() if parts else {}
        if system and system[1]:
            summary.update(system[1].to_dict())
        return summary

    def system_metrics_of(self, verstr):
        """``{sys metric: value}`` of *verstr*, which its row leaves out.
        Shared: copy before changing."""
        system = self.system_metrics.get(verstr)
        return system[0] if system else {}

    def metrics_of(self, verstr):
        """*verstr*'s row's metrics with its ``sys_*`` ones (each at the
        summary its run defines)."""
        metrics = self.row(verstr)["metrics"]
        system = self.system_metrics_of(verstr)
        return {**metrics, **system} if system else metrics

    def outputs_of(self, verstr):
        """``{path: {path, digest, size}}`` of the files *verstr* stored.
        Shared: copy before changing."""
        return self.outputs.get(verstr) or {}

    def features_of(self, verstr):
        """*verstr*'s folded ``features`` value, or None. Shared: copy
        before changing."""
        return self.features.get(verstr)

    def intent_of(self, verstr):
        """*verstr*'s latest ``intent`` value, or None. Shared: copy before
        changing."""
        return self.intents.get(verstr)

    def hypothesis_of(self, verstr):
        """*verstr*'s hypothesis (its first ``create`` entry's), or None."""
        return self.hypotheses.get(verstr)

    def notes_of(self, verstr):
        """*verstr*'s note signatures ``{sig: {count, last_at}}``, the latest
        seen last, or None. Shared: copy before changing."""
        return self.note_sigs.get(verstr)

    def status_of(self, verstr):
        """*verstr*'s derived status, its run state's store write time
        (:attr:`run_state_observed_at`) as *observed_at*."""
        return derive_status(self.run_states.get(verstr),
                             observed_at=self.run_state_observed_at.get(verstr))

    def declared_schema(self):
        """``{metric: {"goal"?, "hidden"?, "chart"?}}`` the runs declare, the latest
        run winning — computed once per snapshot. Shared: copy before
        changing."""
        if not self._declared:
            self._declared.append(runs_declared_schema(self.declared_defs, self.row))
        return self._declared[0]

    def summarized(self, schema):
        """This snapshot with its rows' metrics under the metrics *schema* —
        the same object for the same schema, and this very snapshot when the
        schema changes no row. The shared rows are never touched. Concurrent
        callers with one schema wait for the view in flight and share it."""
        base = self.schema_less()
        if not schema or not base.metric_parts:
            return base
        key = schema_key(schema)
        view = base._views.get(key)
        if view is not None:
            return view
        with base._schema_rows.turn(key):
            view = base._views.get(key)
            if view is None:
                view = base._view(base._schema_rows.rows_in_turn(
                    key, base.rows, base.metric_parts, schema))
                if len(base._views) >= _VIEWS_PER_SNAPSHOT:
                    base._views.clear()
                base._views[key] = view
        return view

    def _view(self, rows):
        if all(a is b for a, b in zip(rows, self.rows)):
            return self
        return replace(
            self, rows=tuple(rows), _by_verstr={r["verstr"]: r for r in rows},
            _views={}, _base=weakref.ref(self), _raw_rows=self.rows,
        )

    def schema_less(self):
        """The snapshot this schema view summarizes (this one when it is no
        view), made again from the view's raw rows once nothing else holds
        it — then a new object each call."""
        if self._base is None:
            return self
        return self._base() or replace(
            self, rows=self._raw_rows, _by_verstr={r["verstr"]: r for r in self._raw_rows},
            _views={}, _base=None, _raw_rows=None,
        )

    @property
    def parent_of(self):
        """``{verstr: parent verstr or None}`` (:attr:`edges`), like
        :class:`~vmn_exp.core.index_point.PointView`'s."""
        return self.edges

    @property
    def children_of(self):
        """``{parent verstr: [child verstr]}`` in storage order, computed once
        per snapshot. Shared: copy before changing."""
        if not self._children:
            self._children.append(
                children_by_parent({"verstr": v, "parent": p} for v, p in self.edges.items())
            )
        return self._children[0]

    def resolve(self, ref, latest=False, kind="experiment"):
        """``(verstr, error)`` for *ref*, like the CLI's ``_resolve_verstr``
        (see :func:`~vmn_exp.core.resolve_ref.resolve_with`)."""
        rows, by_verstr = self.rows, self._by_verstr
        lookups = RefLookups(
            latest=lambda: self._latest(kind)[0],
            at=lambda n: rows[n - 1]["verstr"] if n <= len(rows) else None,
            count=lambda: len(rows),
            exists=by_verstr.__contains__,
            with_prefix=lambda prefix: sorted(v for v in by_verstr if v.startswith(prefix)),
        )
        return resolve_with(lookups, self.app_name, ref, latest, kind)

    def _latest(self, kind):
        if not self.rows:
            return None, no_runs_error(kind, self.app_name)
        newest = max(self.rows, key=lambda r: r.get("timestamp") or "")
        return newest["verstr"], None


def schema_less(snapshot):
    """*snapshot*'s :meth:`IndexSnapshot.schema_less`; anything else (a
    point view, a test double) as it is."""
    of = getattr(snapshot, "schema_less", None)
    return of() if of else snapshot


class RowCache:
    """Materialized snapshot parts shared by successive snapshots.

    A row is re-folded only when its record changed and re-numbered (a
    shallow copy) when it moved, so a heartbeat-only generation reuses every
    row object. The per-verstr maps a snapshot carries are patched for the
    keys that changed and shared with the last snapshot
    (:mod:`~vmn_exp.core.index_snapshot_maps`), as is its rows tuple while
    no row changed, so while the order only grows at its end a generation
    costs O(changed) — at 100k records re-deriving every row's maps took
    ~0.4s per generation, and copying them ~100 MB at 486k. Any other
    reorder rebuilds them from the cached rows.
    """

    def __init__(self):
        self._rows = {}  # key -> lean_row's (row with idx, create note, *side table values)
        self._observed = {}  # key -> (rs_sig, store write time it encodes)
        self._order = []  # the keys of the last snapshot, in order
        self._pos = {}  # key -> its position in _order
        self._list = []  # their rows
        self._tuple, self._list_moved = (), False  # the last snapshot's rows; _list since?
        self._maps = SnapshotMaps()
        self._schema_rows = SchemaRows()  # shared by its snapshots' views

    def pop(self, key, default=None):
        return self._rows.pop(key, default)

    def seed(self, lean):
        """Start from persisted :func:`lean_row` tuples ``{key: (row, ...)}``
        (a warm start, plan 25 F1): those records are not folded again until
        they change."""
        self._rows.update(lean)

    def _row(self, key, idx, record):
        cached = self._rows.get(key)
        if cached is None:
            cached = self._rows[key] = kept_lean(lean_row(idx, record["meta"], record["fold"]))
        elif cached[0]["idx"] != idx:
            cached = self._rows[key] = (dict(cached[0], idx=idx),) + cached[1:]
        return cached

    def _observed_of(self, key, rs_sig):
        cached = self._observed.get(key)
        if cached is None or cached[0] != rs_sig:
            cached = self._observed[key] = (rs_sig, _observed_at(rs_sig))
        return cached[1]

    def snapshot(self, app_name, generation, order, records, touched=None, loading=None):
        """The :class:`IndexSnapshot` of *records* (``{key: record}``) in
        *order*. *touched*: the keys whose record changed since the last
        call; None (unknown) rebuilds every map."""
        grown = touched is not None and order[: len(self._order)] == self._order
        if not (grown and self._patch(touched, records)):
            self._rebuild(order, records)
        for key in order[len(self._list):]:
            self._put(key, len(self._list), records[key])
        self._order = list(order)
        if self._list_moved:
            self._tuple, self._list_moved = tuple(self._list), False
        return IndexSnapshot(
            app_name=app_name, generation=generation, rows=self._tuple,
            _schema_rows=self._schema_rows, loading=loading, **self._maps.shared(),
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
        self._pos, self._list, self._maps = {}, [], SnapshotMaps()
        self._list_moved = True
        live = set(order)
        self._observed = {k: v for k, v in self._observed.items() if k in live}
        for pos, key in enumerate(order):
            self._put(key, pos, records[key])

    def _put(self, key, pos, record):
        row, note, *sides = self._row(key, pos + 1, record)
        if pos == len(self._list):
            self._list.append(row)
            self._list_moved = True
        elif self._list[pos] is not row:
            self._list[pos] = row
            self._list_moved = True
        self._pos[key] = pos
        observed = self._observed_of(key, record["rs_sig"])
        self._maps.put(row, note, sides, record["run_state"], observed)


def _put_sparse(values, verstr, value):
    """Keep *value* under *verstr*, or drop the key when it is empty."""
    if value:
        values[verstr] = value
    else:
        values.pop(verstr, None)


def new_side_tables():
    """Empty side tables, ``{SIDE_TABLES name: {}}``."""
    return {name: {} for name in SIDE_TABLES}


def put_side_tables(tables, verstr, values):
    """Keep *verstr*'s :func:`lean_row` side table *values* in *tables*, as a
    snapshot keeps them (:func:`~vmn_exp.core.index_views.kept_side`)."""
    for name, value in zip(SIDE_TABLES, values):
        _put_sparse(tables[name], verstr, kept_side(name, value))


def _observed_at(rs_sig):
    """The run state's storage mtime from its ``[size, mtime, ...]`` signature."""
    return observed_at_from_mtime(rs_sig[1]) if rs_sig and len(rs_sig) > 1 else None
