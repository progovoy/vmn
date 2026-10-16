#!/usr/bin/env python3
"""The reads of :class:`vmn_exp.core.index_store.SqliteStore` that decode no
record (plan 25 F1): a warm start's lean rows over lazy records, and point
reads on ``exp_rows`` (:mod:`vmn_exp.core.index_point_sql`)."""
import json

from vmn_exp.core import index_point_sql
from vmn_exp.core.index_lazy import STATE_KEYS, LazyRecord
from vmn_exp.core.index_lean_store import read_lean

_CHUNK = 256  # records read per query, under SQLite's bound-parameter limit


class LeanReads:
    """Mixed into the store: uses its ``_read``, ``_conn`` and ``_select``."""

    def load_warm(self, app_name):
        """``(records, keys, lean, stamps)`` for a warm start, or None when
        unavailable: *records* ``{key: LazyRecord}`` (run state only, see
        :mod:`vmn_exp.core.index_lazy`), then the runs' *keys* in storage
        order, their persisted :func:`~vmn_exp.core.index_views.lean_row`
        tuples and ``(timestamp, key)`` sort keys — all read at one
        generation."""
        return self._read(lambda: self._warm(app_name), None)

    def _warm(self, app_name):
        if not self.generation(app_name):
            return None  # never saved: nothing to start warm from
        conn = self._conn
        conn.execute("BEGIN")
        try:
            seqs = dict(conn.execute(
                "SELECT key, seq FROM exp_index WHERE app = ?", (app_name,)
            ).fetchall())
            states = dict(self._select("exp_index_state", app_name))
            keys, lean, stamps = read_lean(conn, app_name)
        finally:
            conn.execute("COMMIT")
        fetch = _Prefetch(self, app_name, seqs)
        records = {
            key: LazyRecord(key, _state_from(states.get(key)), fetch, key in lean)
            for key in seqs
        }
        return records, keys, lean, stamps

    def records_parts(self, app_name, seqs):
        """``{key: (head JSON, fold JSON)}`` of the records of *seqs*
        (``{key: seq}``) still stored at that seq; ``{}`` when unavailable."""
        return self._read(lambda: {
            key: (head, data)
            for key, seq, head, data in self._conn.execute(
                "SELECT key, seq, head, data FROM exp_index WHERE app = ?"
                f" AND key IN ({', '.join('?' * len(seqs))})", (app_name, *seqs),
            )
            if seqs[key] == seq
        }, {})

    def keys(self, app_name):
        """Every persisted record key of *app_name*; None when unavailable."""
        return self._read(lambda: {key for (key,) in self._conn.execute(
            "SELECT key FROM exp_index WHERE app = ?", (app_name,)
        )}, None)

    def resolve_one(self, app_name, ref, latest=False, kind="experiment"):
        """``(verstr, error)`` for *ref* like
        :meth:`~vmn_exp.core.index_snapshot.IndexSnapshot.resolve`, each kind
        of ref one indexed query on ``exp_rows``; None when unavailable."""
        return self._read(
            lambda: index_point_sql.resolve(self._conn, app_name, ref, latest, kind), None
        )

    def lean_row_of(self, app_name, verstr):
        """*verstr*'s persisted lean row (``idx`` set), or None."""
        return self._read(lambda: index_point_sql.row_of(self._conn, app_name, verstr), None)

    def parent_of(self, app_name, verstr):
        """*verstr*'s persisted parent, or None."""
        return self._read(
            lambda: index_point_sql.parent_of(self._conn, app_name, verstr), None
        )

    def children_of(self, app_name, verstr):
        """The runs whose parent is *verstr*, in storage order."""
        return self._read(
            lambda: index_point_sql.children_of(self._conn, app_name, verstr), []
        )


class _Prefetch:
    """A warm start's records' stored parts, read a chunk at a time: a
    refresh that touches one record usually touches the ones after it next
    (a full listing walks them all), and one query per record cost more than
    decoding them all."""

    def __init__(self, store, app_name, seqs):
        self._store, self._app, self._seqs = store, app_name, seqs
        self._order = list(seqs)
        self._pos = {key: n for n, key in enumerate(self._order)}
        self._asked, self._ready = set(), {}

    def __call__(self, key):
        """*key*'s ``(head JSON, fold JSON)``, or None (see
        :class:`~vmn_exp.core.index_lazy.LazyRecord`)."""
        if key not in self._asked:
            self._read_from(self._pos[key])
        return self._ready.pop(key, None)

    def _read_from(self, start):
        chunk = []
        for key in self._order[start:]:
            if key not in self._asked:
                chunk.append(key)
                if len(chunk) == _CHUNK:
                    break
        self._asked.update(chunk)
        self._ready.update(
            self._store.records_parts(self._app, {key: self._seqs[key] for key in chunk})
        )


def _state_from(data):
    state = dict.fromkeys(STATE_KEYS)
    if data is not None:
        state.update(json.loads(data))
    return state
