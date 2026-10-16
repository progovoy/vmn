#!/usr/bin/env python3
"""What a similar-runs query reads of the runs besides its FTS table: their
rows, facts, statuses, trees and declared goals.

:class:`SnapshotRows` reads them off an index snapshot. :class:`StoreRows` reads the few
runs a query looks at from the persisted index's lean tables (``exp_rows``,
``exp_sides``, ``exp_index_state``), one batched query each (the shown
runs' facts and states: :meth:`StoreRows.prefetch`), so a fresh process
answers without loading the app. Rows are shared: copy to change.
A run's tree root is the top of its ``parent`` chain (a parent missing from
the app ends it), a run with neither parent nor children its own.
"""
import json

from vmn_exp.core import index_list_sql
from vmn_exp.core.index_lean_store import NOTE, decode_row, run_status
from vmn_exp.core.index_views import runs_declared_schema
from vmn_exp.core.similar_filing import snapshot_facts
from vmn_exp.core.sqlite_conn import in_chunks

# The side tables a run's facts read (constants, inlined in the query).
_FACT_KINDS = ", ".join(f"'{kind}'" for kind in ("features", "intents", "hypotheses", NOTE))


class SnapshotRows:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self._lookup = snapshot.row
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
        return self.snapshot.status_of(verstr)

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
        return self.snapshot.declared_schema()


class StoreRows:
    """The runs of *app* as the index file *conn* holds them."""

    def __init__(self, conn, app):
        self._conn, self._app = conn, app
        self._rows, self._keys, self._roots, self._states, self._facts = {}, {}, {}, {}, {}
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

    def prefetch(self, rows):
        """Read the facts and run states of *rows* (about to be shown) in
        one query each."""
        verstrs = [row["verstr"] for row in rows]
        self.rows_of(verstrs)
        self._read_facts([v for v in dict.fromkeys(verstrs) if v not in self._facts])
        self._read_states([v for v in dict.fromkeys(verstrs) if v not in self._states])

    def _by_key(self, verstrs):
        return {self._keys[v]: v for v in verstrs if v in self._keys}

    def _read_facts(self, verstrs):
        self._facts.update((v, {}) for v in verstrs)
        by_key = self._by_key(verstrs)
        for key, kind, data in self._select(
                "SELECT key, kind, data FROM exp_sides WHERE app = ? AND key IN ({marks})"
                f" AND kind IN ({_FACT_KINDS})", list(by_key)):
            self._facts[by_key[key]][kind] = json.loads(data)

    def _read_states(self, verstrs):
        self._states.update((v, {}) for v in verstrs)
        by_key = self._by_key(verstrs)
        for key, data in self._select(
                "SELECT key, data FROM exp_index_state WHERE app = ? AND key IN ({marks})",
                list(by_key)):
            self._states[by_key[key]] = json.loads(data)

    def _state(self, verstr):
        if verstr not in self._states:
            self.row(verstr)
            self._read_states([verstr])
        return self._states[verstr]

    def facts(self, row):
        verstr = row["verstr"]
        if verstr not in self._facts:
            self.prefetch([row])
        sides = self._facts[verstr]
        command = row.get("command") or (self._state(verstr).get("run_state")
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
            defs, rows = index_list_sql.declared(self._conn, self._app)
            self._declared = runs_declared_schema(defs, rows.get)
        return self._declared
