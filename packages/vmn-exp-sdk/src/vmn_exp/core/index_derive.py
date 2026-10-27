#!/usr/bin/env python3
"""Re-deriving an index file's derived tables (``exp_rows``, ``exp_sides``,
``similar_*``) from its persisted records, after an upgrade of
:data:`~vmn_exp.core.index_store_schema.DERIVED_VERSION`: nothing is dropped
and storage is never read.

The upgrade leaves a marker per app in ``exp_index_kv`` (scope ``derive:<app>``,
payload ``{"after": <key>}``): the app's records past ``after``, in key order,
are still to re-derive. :func:`derive_chunk` takes the next :data:`CHUNK` of
them: reads and decodes them in a read transaction, derives their rows, then
writes those in one short write transaction — skipping a record saved again
since it was read (that save wrote its own rows) — and moves the marker on.
Once past the last record, ``idx`` is renumbered (:data:`CHUNK` rows per
transaction) and the marker dropped. Until then the persisted rows are not
read (warm starts, point reads and listings wait for the marker to go): an
app's index re-derives its rows before loading them.
"""
import json
import sqlite3
import threading

from vmn_exp.core.index_lean_store import apply_numbers, leans_of, renumbered, write_lean
from vmn_exp.core.index_store_kv import write_puts
from vmn_exp.core.index_store_reads import RECORD_PARTS_SQL
from vmn_exp.core.index_store_schema import DERIVE_SCOPE, SCHEMA_VERSION
from vmn_exp.core.similar_filing import file_records
from vmn_exp.core.sqlite_conn import in_chunks, read_tx, write_tx

CHUNK = 500
_LOCKS = {}  # (file, app) -> the lock its derivers in this process take turns under
_LOCKS_LOCK = threading.Lock()
_CHUNK_SQL = f"{RECORD_PARTS_SQL} AND i.key > ? ORDER BY i.key LIMIT ?"


def pending_after(conn, app):
    """The key *app*'s re-derive is past (``""``: none yet), or None when
    nothing is left to re-derive."""
    row = conn.execute(
        "SELECT payload FROM exp_index_kv WHERE scope = ?", (DERIVE_SCOPE + app,)
    ).fetchone()
    return None if row is None else json.loads(row[0]).get("after", "")


def pending_apps(conn):
    """The apps left to re-derive."""
    return [scope[len(DERIVE_SCOPE):] for (scope,) in conn.execute(
        "SELECT scope FROM exp_index_kv WHERE substr(scope, 1, ?) = ?",
        (len(DERIVE_SCOPE), DERIVE_SCOPE))]


def decoded_chunk(conn, app, after, size):
    """``({key: seq}, {key: record})`` of *app*'s *size* records past *after*."""
    from vmn_exp.core.index_store import decode_records  # index_store builds on this

    with read_tx(conn):
        rows = conn.execute(_CHUNK_SQL, (app, after, size)).fetchall()
    records = decode_records([(key, head, data) for key, _, head, data, _ in rows],
                             [(key, state) for key, *_, state in rows if state is not None])
    return {key: seq for key, seq, *_ in rows}, records


def derive_chunk(conn, app):
    """Re-derive *app*'s next chunk; how many records it took, 0 once
    nothing is left (see the module)."""
    after = pending_after(conn, app)
    if after is None:
        return 0
    seqs, records = decoded_chunk(conn, app, after, CHUNK)
    if not seqs:
        _finish(conn, app)
        return 0
    leans = leans_of(records)
    with write_tx(conn):
        if pending_after(conn, app) == after:  # else another deriver took this chunk
            fresh = {key: records[key] for key, seq in _seqs(conn, app, seqs).items()
                     if seq == seqs[key]}
            mine = {key: leans[key] for key in fresh if key in leans}
            write_lean(conn, app, _generation(conn, app), fresh, (), {}, mine, renumber=False)
            file_records(conn, app, fresh, (), leans=mine)
            _move_marker(conn, app, max(seqs))
    return len(seqs)


def _seqs(conn, app, keys):
    out = {}
    for chunk, marks in in_chunks(keys):
        out.update(conn.execute(
            f"SELECT key, seq FROM exp_index WHERE app = ? AND key IN ({marks})", (app, *chunk)))
    return out


def _generation(conn, app):
    row = conn.execute("SELECT gen FROM exp_index_gen WHERE app = ?", (app,)).fetchone()
    return row[0] if row else 0


def _move_marker(conn, app, after):
    write_puts(conn, [(DERIVE_SCOPE + app, SCHEMA_VERSION, {"after": after})])


def _finish(conn, app):
    with read_tx(conn):
        moves = renumbered(conn, app)
    for i in range(0, len(moves), CHUNK):
        with write_tx(conn):
            apply_numbers(conn, moves[i:i + CHUNK])
    with write_tx(conn):
        conn.execute("DELETE FROM exp_index_kv WHERE scope = ?", (DERIVE_SCOPE + app,))


def _lock_of(file, app):
    with _LOCKS_LOCK:
        return _LOCKS.setdefault((file, app), threading.Lock())


class Rederive:
    """Mixed into the store: uses its ``_read``, ``_conn`` and ``_db``."""

    def deriving(self, app_name):
        """Whether an upgrade left *app_name*'s derived tables to re-derive.
        Only opening a file marks apps, so one seen clear stays clear for as
        long as the connection: hot paths ask once per app, not per read."""
        conn = self._db.get()
        if conn is None:
            return False
        clear = getattr(self, "_derived_on", None)
        if clear is None or clear[0] is not conn:
            clear = self._derived_on = (conn, set())
        if app_name in clear[1]:
            return False
        try:
            pending = pending_after(conn, app_name) is not None
        except sqlite3.Error as exc:
            self._db.on_error(exc)
            return False
        if not pending:
            clear[1].add(app_name)
        return pending

    def pending_apps(self):
        """The apps an upgrade left to re-derive."""
        return self._read(lambda: pending_apps(self._conn), [])

    def derive(self, app_name, progress=None):
        """Re-derive *app_name*'s derived tables (see the module), calling
        *progress(done, total)* before each chunk; True when they are (or
        were) re-derived, False when the file failed under it."""
        conn = self._db.get()
        if conn is None:
            return False
        with _lock_of(self._db.file, app_name):
            try:
                return self._derive(conn, app_name, progress)
            except (sqlite3.Error, ValueError) as exc:
                self._db.on_error(exc, "Could not re-derive the experiment index {file}"
                                       " ({exc}); reading its records instead")
                return False

    def _derive(self, conn, app_name, progress):
        after = pending_after(conn, app_name)
        if after is None:
            return True
        (total,) = conn.execute(
            "SELECT COUNT(*) FROM exp_index WHERE app = ?", (app_name,)).fetchone()
        (done,) = conn.execute(
            "SELECT COUNT(*) FROM exp_index WHERE app = ? AND key <= ?",
            (app_name, after)).fetchone()
        while True:
            if progress is not None:
                progress(done, total)
            taken = derive_chunk(conn, app_name)
            if not taken:
                return True
            done = min(done + taken, total)
            self._db.tidy_wal()
