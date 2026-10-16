#!/usr/bin/env python3
"""The reads of :class:`vmn_exp.core.index_store.SqliteStore` that decode no
record (plan 25 F1): a warm start's lean rows over lazy records, and point
reads on ``exp_rows`` (:mod:`vmn_exp.core.index_point_sql`)."""
import json

from vmn_exp.core import index_point_sql
from vmn_exp.core.index_lazy import STATE_KEYS, LazyRecord
from vmn_exp.core.index_lean_store import read_lean


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
        fetch = lambda key: self.record_parts(app_name, key, seqs[key])  # noqa: E731
        records = {
            key: LazyRecord(key, _state_from(states.get(key)), fetch) for key in seqs
        }
        return records, keys, lean, stamps

    def record_parts(self, app_name, key, seq):
        """``(head JSON, fold JSON)`` of *key* as stored at *seq*; None when
        it was rewritten or removed since, or unavailable."""
        return self._read(lambda: self._conn.execute(
            "SELECT head, data FROM exp_index WHERE app = ? AND key = ? AND seq = ?",
            (app_name, key, seq),
        ).fetchone(), None)

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


def _state_from(data):
    state = dict.fromkeys(STATE_KEYS)
    if data is not None:
        state.update(json.loads(data))
    return state
