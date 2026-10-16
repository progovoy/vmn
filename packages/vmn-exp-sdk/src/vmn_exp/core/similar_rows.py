#!/usr/bin/env python3
"""What a similar-runs query reads of the runs besides its FTS table: their
rows, facts, statuses, trees and declared goals.

:class:`SnapshotRows` reads them off an index snapshot (duck-typed: ``.rows``
and, when it has them, ``.row``, ``.features_of``/``.intent_of``/
``.hypothesis_of``, ``.run_states``, ``.run_state_observed_at``,
``.create_notes``, ``.declared_schema``). :class:`StoreRows` reads the few
runs a query looks at from the persisted index's lean tables (``exp_rows``,
``exp_sides``, ``exp_index_state``), one batched query each, so a fresh
process answers without loading the app. Rows are shared: copy to change.
A run's tree root is the top of its ``parent`` chain (a parent missing from
the app ends it), a run with neither parent nor children its own.
"""
import json

from vmn_exp.core.index_lean_store import NOTE, decode_row, run_status
from vmn_exp.core.index_views import runs_declared_schema
from vmn_exp.core.similar_filing import snapshot_facts
from vmn_exp.core.sqlite_conn import in_chunks
from vmn_exp.core.status import derive_status

class SnapshotRows:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        lookup = getattr(snapshot, "row", None)
        self._by_verstr = None if callable(lookup) else {r["verstr"]: r for r in snapshot.rows}
        self._lookup = lookup if callable(lookup) else self._by_verstr.get
        self._parents = None
        self._roots = {}

    def row(self, verstr):
        return self._lookup(verstr)

    def rows_of(self, verstrs):
        found = ((v, self._lookup(v)) for v in verstrs)
        return {v: row for v, row in found if row is not None}

    def facts(self, row):
        return snapshot_facts(self.snapshot, row)

    def status_of(self, verstr):
        of = getattr(self.snapshot, "status_of", None)
        if of is not None:
            return of(verstr)
        states = getattr(self.snapshot, "run_states", None) or {}
        return derive_status(states.get(verstr))

    def parents_among(self, verstrs):
        if self._parents is None:
            self._parents = {r["parent"] for r in self.snapshot.rows if r.get("parent")}
        return {v for v in verstrs if v in self._parents}

    def root(self, row):
        verstr, chain, node = row.get("verstr"), [], row
        while True:
            parent = node.get("parent")
            if not parent or parent in chain or parent == node.get("verstr"):
                top = node.get("verstr")
                break
            if parent in self._roots:
                top = self._roots[parent]
                break
            chain.append(parent)
            above = self._lookup(parent)
            if above is None:
                top = parent
                break
            node = above
        self._roots.update(dict.fromkeys(chain, top))
        return top or verstr

    def declared_schema(self):
        declared = getattr(self.snapshot, "declared_schema", None)
        return declared() if declared else {}


class StoreRows:
    """The runs of *app* as the index file *conn* holds them."""

    def __init__(self, conn, app):
        self._conn, self._app = conn, app
        self._rows, self._keys, self._roots, self._states = {}, {}, {}, {}
        self._declared = None

    def _select(self, sql, values):
        for chunk, marks in in_chunks(values):
            yield from self._conn.execute(sql.format(marks=marks), (self._app, *chunk))

    def rows_of(self, verstrs):
        wanted = [v for v in dict.fromkeys(verstrs) if v not in self._rows]
        for key, verstr, idx, root, row in self._select(
                "SELECT key, verstr, idx, root, row FROM exp_rows WHERE app = ?"
                " AND verstr IN ({marks})", wanted):
            row = decode_row(idx, row)
            self._rows[verstr], self._keys[verstr], self._roots[verstr] = row, key, root
        return {v: self._rows[v] for v in verstrs if v in self._rows}

    def row(self, verstr):
        return self.rows_of([verstr]).get(verstr)

    def _sides(self, verstr):
        out = {}
        key = self._keys.get(verstr)
        if key is not None:
            for kind, data in self._conn.execute(
                    "SELECT kind, data FROM exp_sides WHERE app = ? AND key = ?",
                    (self._app, key)):
                out[kind] = json.loads(data)
        return out

    def _state(self, verstr):
        if verstr not in self._states:
            self.row(verstr)
            found = self._conn.execute(
                "SELECT data FROM exp_index_state WHERE app = ? AND key = ?",
                (self._app, self._keys.get(verstr))).fetchone()
            self._states[verstr] = json.loads(found[0]) if found else {}
        return self._states[verstr]

    def facts(self, row):
        sides = self._sides(row["verstr"])
        command = row.get("command") or (self._state(row["verstr"]).get("run_state")
                                         or {}).get("command")
        return (sides.get("features"), sides.get("intents"), sides.get("hypotheses"), command,
                sides.get(NOTE))

    def status_of(self, verstr):
        return run_status(self._state(verstr)) or "created"

    def parents_among(self, verstrs):
        return {p for (p,) in self._select(
            "SELECT DISTINCT parent FROM exp_rows WHERE app = ? AND parent IN ({marks})",
            list(dict.fromkeys(verstrs)))}

    def root(self, row):
        verstr = row.get("verstr")
        if verstr in self.rows_of([verstr]):
            return self._roots[verstr] or verstr
        parent = row.get("parent")
        if not parent:
            return verstr
        return self.root(self.row(parent) or {"verstr": parent})

    def declared_schema(self):
        if self._declared is None:
            declared, stamps = {}, {}
            for verstr, ts, idx, data in self._conn.execute(
                    "SELECT r.verstr, r.timestamp, r.idx, s.data FROM exp_sides s"
                    " JOIN exp_rows r ON r.app = s.app AND r.key = s.key"
                    " WHERE s.app = ? AND s.kind = 'declared_defs'", (self._app,)):
                declared[verstr], stamps[verstr] = json.loads(data), {"timestamp": ts, "idx": idx}
            self._declared = runs_declared_schema(declared, stamps.get)
        return self._declared
