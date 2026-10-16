#!/usr/bin/env python3
"""What fills the similar-runs tables (:mod:`vmn_exp.core.similar_fts`).

- :func:`file_records` — the experiment index's save hook, in the save's
  transaction: its changed runs are filed (a document that files the same
  writes nothing), its removed records and changed non-runs forgotten, and a
  run whose run state now names another command refiled (the command lives
  in the run state, which a refresh may save on its own).
- :func:`file_lean` — refiles an app from the index's lean tables, when
  documents are missing or another profile version filed them.
- :class:`SnapshotFiler` — keeps a database (a ``:memory:`` one, or a
  server's host-local file) in step with a lineage of index snapshots,
  refiling the runs whose row or side values are other objects than at the
  last sync.
"""
import itertools
import json
import weakref

from vmn_exp.core import similar_fts
from vmn_exp.core.index_lean_store import is_run, read_lean
from vmn_exp.core.index_views import SIDE_TABLES, lean_row
from vmn_exp.core.similar_doc import build_doc
from vmn_exp.core.sqlite_conn import write_tx

_FEATURES, _INTENTS, _HYPOTHESES = (SIDE_TABLES.index(k) for k in
                                    ("features", "intents", "hypotheses"))


def _command(state):
    return (state or {}).get("command") if isinstance(state, dict) else None


def lean_doc(row, note, sides, command):
    """The doc of a run from its lean row, create *note*, side values (in
    :data:`~vmn_exp.core.index_views.SIDE_TABLES` order) and *command*."""
    return build_doc(row, sides[_FEATURES], sides[_INTENTS], sides[_HYPOTHESES],
                     command=row.get("command") or command, create_note=note)


def _record_doc(record, lean=None):
    row, note, *sides = lean or lean_row(0, record["meta"], record["fold"])
    return lean_doc(row, note, sides, _command(record.get("run_state")))


def file_records(conn, app, changed, removed, states=None, leans=None):
    """Bring *app*'s documents in line with a save (see the module); *leans*:
    the changed runs' lean rows, when already derived."""
    if not similar_fts.has_tables(conn):
        return
    runs = {key: r for key, r in changed.items() if is_run(r)}
    similar_fts.forget(conn, app, list(removed) + [k for k in changed if k not in runs])
    moved = _commands_moved(conn, app, {k: r for k, r in (states or {}).items()
                                        if k not in changed})
    runs.update((key, record) for key, record in moved.items() if is_run(record))
    commands = {key: _command(r.get("run_state")) for key, r in runs.items()}
    leans = leans or {}
    similar_fts.file_docs(conn, app, [(key, _record_doc(r, leans.get(key)))
                                      for key, r in runs.items()], commands)


def _commands_moved(conn, app, states):
    """The *states* records whose run state names another command than their
    document was filed with (a record never filed is left to its next save)."""
    named = {key: json.dumps(_command(r.get("run_state")), default=str)
             for key, r in states.items() if _command(r.get("run_state"))}
    if not named:
        return {}
    filed = similar_fts.filed(conn, app, list(named), "cmd")
    return {key: states[key] for key, (cmd,) in filed.items() if cmd != named[key]}


def file_lean(conn, app):
    """Refile every run of *app* from the index's lean tables (``exp_rows``,
    ``exp_sides``, ``exp_index_state``), forgetting documents of runs gone."""
    keys, lean, _ = read_lean(conn, app)
    states = {key: json.loads(data) for key, data in conn.execute(
        "SELECT key, data FROM exp_index_state WHERE app = ?", (app,))}
    entries, commands = [], {}
    for key in keys:
        row, note, *sides = lean[key]
        commands[key] = _command((states.get(key) or {}).get("run_state"))
        entries.append((key, lean_doc(row, note, sides, commands[key])))
    similar_fts.forget_except(conn, app, set(keys))
    similar_fts.file_docs(conn, app, entries, commands)


def _states_of(snapshot):
    return getattr(snapshot, "run_states", None) or {}


def snapshot_facts(snapshot, row):
    """``(features, intent, hypothesis, command, create note)`` of a run of
    *snapshot* (a missing accessor reads as None)."""
    verstr = row["verstr"]

    def side(name):
        of = getattr(snapshot, name, None)
        return of(verstr) if of else None
    notes = getattr(snapshot, "create_notes", None) or {}
    command = row.get("command") or _command(_states_of(snapshot).get(verstr))
    return (side("features_of"), side("intent_of"), side("hypothesis_of"), command,
            notes.get(verstr))


_TOKENS = itertools.count()


class SnapshotFiler:
    """Files *app*'s runs of successive snapshots into *conn* (see the module)."""

    def __init__(self, conn, app):
        self.conn, self.app = conn, app
        self._seen = {}  # verstr -> (row, features, intent, hypothesis, command, note)
        self._synced = None  # a weak reference to the last snapshot synced
        self.syncs = 0  # syncs that filed or forgot anything
        self.token = next(_TOKENS)  # this filer, unlike its id(), is never reused

    def synced_to(self, snapshot):
        """Whether the last snapshot synced is *snapshot*."""
        return self._synced is not None and self._synced() is snapshot

    def sync(self, snapshot):
        """File what changed since the last snapshot synced; one transaction."""
        if self.synced_to(snapshot):
            return
        entries, commands, seen = [], {}, {}
        for row in snapshot.rows:
            verstr = row["verstr"]
            facts = snapshot_facts(snapshot, row)
            mark = (row, *facts)
            seen[verstr] = mark
            old = self._seen.get(verstr)
            if old is not None and all(a is b or a == b for a, b in zip(old, mark)):
                continue
            features, intent, hypothesis, command, note = facts
            commands[verstr] = command
            entries.append((verstr, build_doc(row, features, intent, hypothesis,
                                              command=command, create_note=note)))
        gone = [v for v in self._seen if v not in seen]
        if not self._seen:  # a file filed before this process: forget what it no longer has
            gone = [key for (key,) in self.conn.execute(
                "SELECT key FROM similar_doc WHERE app = ?", (self.app,)) if key not in seen]
        with write_tx(self.conn):
            similar_fts.forget(self.conn, self.app, gone)
            similar_fts.file_docs(self.conn, self.app, entries, commands)
        self._seen, self._synced = seen, weakref.ref(snapshot)
        if entries or gone:
            self.syncs += 1
