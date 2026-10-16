#!/usr/bin/env python3
"""The reads of :class:`vmn_exp.core.index_store.SqliteStore` that decode no
record (plan 25 F1): a warm start's lean rows over lazy records, and point
reads on ``exp_rows`` (:mod:`vmn_exp.core.index_point_sql`)."""
import itertools
import threading
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

    def load_lazy(self, app_name):
        """``{key: LazyRecord}`` with nothing read, run states included —
        what a refresh that builds no snapshot starts from — or None when
        never saved or unavailable."""
        return self._read(lambda: self._lazy(app_name), None)

    def _lazy(self, app_name):
        if not self.generation(app_name):
            return None
        # Keys alone come off the primary key's index, never the table's pages.
        seqs = dict.fromkeys(key for (key,) in self._conn.execute(
            "SELECT key FROM exp_index WHERE app = ?", (app_name,)
        ))
        fetch = _Prefetch(self, app_name, seqs, first_chunk=1)
        return {key: LazyRecord(key, None, fetch, None) for key in seqs}

    def listing(self, app_name, read):
        """``read(conn)``'s answer, all of it read at one generation; None
        when unavailable or the app was never saved."""
        return self._read(lambda: self._at_one_generation(app_name, read), None)

    def _at_one_generation(self, app_name, read):
        if not self.generation(app_name):
            return None
        self._conn.execute("BEGIN")
        try:
            return read(self._conn)
        finally:
            self._conn.execute("COMMIT")

    def records_parts(self, app_name, seqs):
        """``{key: (head JSON, fold JSON, run state JSON or None)}`` of the
        records of *seqs* (``{key: seq}``) still stored at that seq (a None
        seq: as stored now); ``{}`` when unavailable."""
        return self._read(lambda: {
            key: (head, data, state)
            for key, seq, head, data, state in self._conn.execute(
                "SELECT i.key, i.seq, i.head, i.data, s.data FROM exp_index i"
                " LEFT JOIN exp_index_state s ON s.app = i.app AND s.key = i.key"
                f" WHERE i.app = ? AND i.key IN ({', '.join('?' * len(seqs))})",
                (app_name, *seqs),
            )
            if seqs[key] in (None, seq)
        }, {})

    def diff_keys(self, app_name, names):
        """``(names not persisted, persisted keys not in names)`` of
        *app_name* against the set *names*; None when unavailable."""
        return self._read(lambda: self._diff(app_name, names), None)

    def _diff(self, app_name, names):
        query = "SELECT key FROM exp_index WHERE app = ?"
        gone, known = [], 0
        for (key,) in self._conn.execute(query, (app_name,)):
            if key in names:
                known += 1
            else:
                gone.append(key)
        if known == len(names):  # every name is persisted (the usual case)
            return [], gone
        persisted = {key for (key,) in self._conn.execute(query, (app_name,))}
        return [name for name in names if name not in persisted], gone

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

    def __init__(self, store, app_name, seqs, first_chunk=_CHUNK):
        """*first_chunk*: how many records a read takes at first; it doubles
        (up to a full chunk) while the reads go on in order, and falls back
        when one jumps — a refresh that reads a few scattered records reads
        just those."""
        self._store, self._app, self._seqs = store, app_name, seqs
        self._order = list(seqs)
        self._pos = {key: n for n, key in enumerate(self._order)}
        self._asked, self._ready = set(), {}
        self._first = self._size = first_chunk
        self._next = None  # the position right after the last read
        # Refreshes run on a thread pool: a key whose chunk another thread is
        # reading waits for that read instead of finding nothing ready yet.
        self._lock = threading.Lock()

    def __call__(self, key):
        """*key*'s ``(head JSON, fold JSON, run state JSON)``, or None (see
        :class:`~vmn_exp.core.index_lazy.LazyRecord`)."""
        with self._lock:
            if key not in self._asked:
                self._read_from(self._pos[key])
            return self._ready.pop(key, None)

    def _read_from(self, start):
        in_order = start == self._next
        self._size = min(self._size * 2, _CHUNK) if in_order else self._first
        chunk, end = [], start
        for end, key in enumerate(itertools.islice(self._order, start, None), start + 1):
            if key not in self._asked:
                chunk.append(key)
                if len(chunk) == self._size:
                    break
        self._next = end
        self._asked.update(chunk)
        self._ready.update(
            self._store.records_parts(self._app, {key: self._seqs[key] for key in chunk})
        )


def _state_from(data):
    state = dict.fromkeys(STATE_KEYS)
    if data is not None:
        state.update(json.loads(data))
    return state
