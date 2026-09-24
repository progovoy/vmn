#!/usr/bin/env python3
"""An immutable view of an :class:`~version_stamp.core.experiment_index.ExperimentIndex`
at one generation.

The index builds one per generation and swaps it in whole, so a reader holds a
consistent set of rows, run states and parent edges without taking the index
lock or touching storage. Rows are shared between readers: treat them (and the
dicts here) as read-only and copy before changing anything.
"""
from dataclasses import dataclass, field

from version_stamp.core.experiment_fold import fold_row


@dataclass(frozen=True, eq=False)
class IndexSnapshot:
    app_name: str
    generation: int
    rows: tuple  # experiment_row dicts in storage order, idx set
    run_states: dict  # {verstr: raw run state or None}
    edges: dict  # {verstr: parent verstr or None}
    create_notes: dict = field(default_factory=dict, repr=False)
    _by_verstr: dict = field(default_factory=dict, repr=False)

    @classmethod
    def build(cls, app_name, generation, rows, run_states, create_notes=None):
        rows = tuple(rows)
        return cls(
            app_name=app_name,
            generation=generation,
            rows=rows,
            run_states=run_states,
            edges={row["verstr"]: row.get("parent") for row in rows},
            create_notes=create_notes or {},
            _by_verstr={row["verstr"]: row for row in rows},
        )

    def row(self, verstr):
        """The row of *verstr*, or None."""
        return self._by_verstr.get(verstr)

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
    """Materialized rows shared by successive snapshots: a row is re-folded
    only when its record changed and re-numbered (a shallow copy) when it
    moved, so a heartbeat-only generation reuses every row object."""

    def __init__(self):
        self._rows = {}  # key -> (row with idx, create note)

    def pop(self, key, default=None):
        return self._rows.pop(key, default)

    def _row(self, key, idx, record):
        cached = self._rows.get(key)
        if cached is None:
            row = fold_row(idx, record["meta"], record["fold"], True)
            cached = self._rows[key] = (row, row.pop("create_note"))
        elif cached[0]["idx"] != idx:
            cached = self._rows[key] = (dict(cached[0], idx=idx), cached[1])
        return cached

    def snapshot(self, app_name, generation, order, records):
        """The :class:`IndexSnapshot` of *records* (``{key: record}``) in *order*."""
        rows, notes, states = [], {}, {}
        for idx, key in enumerate(order, 1):
            row, note = self._row(key, idx, records[key])
            rows.append(row)
            notes[row["verstr"]] = note
            states[row["verstr"]] = records[key]["run_state"]
        return IndexSnapshot.build(app_name, generation, rows, states, notes)
