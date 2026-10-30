#!/usr/bin/env python3
"""The persisted rows a warm restart serves before reading them all back
(:mod:`vmn_exp.core.index_first_rows`): whole trees around the newest runs.

The newest runs of a sweep-heavy app are all trials, so on their own they
show no outer run: the Outer runs view read "No runs yet" and every trial's
parent was missing. Beside the newest *limit* runs this reads their ancestors
up to the root and the newest :data:`OUTER_RUNS` outer runs, each with one
child (what makes it read as one), at most *max_rows* in all — a fixed
number of indexed queries: the timestamp index for the newest, the
``verstr`` one for parents, the ``root`` one (one seek per distinct root, at
most :data:`ROOTS_SEEN`) for the outer runs and the ``parent`` one for a
child. Only the total is counted over every row.
"""
from vmn_exp.core import index_lean_store as lean_store
from vmn_exp.core.sqlite_conn import in_chunks

OUTER_RUNS = 100  # the newest outer runs served beside the newest runs
ROOTS_SEEN = 2000  # distinct roots ranked for them (one index seek each)
_COLUMNS = "key, idx, timestamp, verstr, parent, row"
# The distinct roots, one seek of the (app, root) index each.
_ROOTS_SQL = (
    "WITH RECURSIVE roots(r) AS ("
    " SELECT MIN(root) FROM exp_rows WHERE app = ?1"
    " UNION ALL SELECT (SELECT MIN(root) FROM exp_rows WHERE app = ?1 AND root > roots.r)"
    " FROM roots WHERE roots.r IS NOT NULL LIMIT ?2"
    ") SELECT r FROM roots WHERE r IS NOT NULL"
)


def read_first_rows(conn, app, limit, max_rows):
    """``(runs, {key: lean_row tuple})``: how many runs *app* has, and its
    first rows (see the module) in storage order, numbered as
    :func:`~vmn_exp.core.index_lean_store.read_lean` numbers them."""
    (runs,) = conn.execute("SELECT COUNT(*) FROM exp_rows WHERE app = ?", (app,)).fetchone()
    newest = conn.execute(
        f"SELECT {_COLUMNS} FROM exp_rows WHERE app = ? ORDER BY timestamp DESC, key DESC LIMIT ?",
        (app, min(limit, max_rows)),
    ).fetchall()
    first = runs - len(newest) + 1  # their rank: the column may be left stale
    picked = _Picked(max_rows)
    picked.add([(key, first + n, *rest) for n, (key, _, *rest) in enumerate(newest[::-1])])
    _add_ancestors(conn, app, picked)
    _add_outer_runs(conn, app, picked)
    return runs, _decoded(conn, app, picked.rows)


class _Picked:
    """The rows read so far, ``{verstr: (key, idx, timestamp, verstr,
    parent, row)}``, at most *cap*."""

    def __init__(self, cap):
        self.rows, self.cap = {}, cap

    def room(self):
        return self.cap - len(self.rows)

    def add(self, rows):
        for row in rows[:max(self.room(), 0)]:
            self.rows.setdefault(row[3], row)

    def missing_parents(self):
        return {row[4] for row in self.rows.values() if row[4] and row[4] not in self.rows}


def _by_verstr(conn, app, verstrs, columns=_COLUMNS):
    return [row for chunk, marks in in_chunks(verstrs) for row in conn.execute(
        f"SELECT {columns} FROM exp_rows WHERE app = ? AND verstr IN ({marks})", (app, *chunk))]


def _add_ancestors(conn, app, picked):
    """Every picked row's parent, up to its root (while there is room)."""
    seen = set()
    while picked.room() > 0:
        parents = picked.missing_parents() - seen
        if not parents:
            return
        seen |= parents
        picked.add(_by_verstr(conn, app, sorted(parents)))


def _add_outer_runs(conn, app, picked):
    """The newest outer runs not picked yet, each with a child."""
    roots = [r for (r,) in conn.execute(_ROOTS_SQL, (app, ROOTS_SEEN))]
    ranked = sorted(_by_verstr(conn, app, roots, "timestamp, key, verstr"), reverse=True)
    parents = {row[4] for row in picked.rows.values()}
    for _, _, verstr in ranked[:OUTER_RUNS]:
        needed = (verstr not in picked.rows) + (verstr not in parents)
        if picked.room() < needed:
            return
        if verstr not in picked.rows:
            picked.add(_by_verstr(conn, app, [verstr]))
        if verstr not in parents:
            picked.add(conn.execute(
                f"SELECT {_COLUMNS} FROM exp_rows WHERE app = ? AND parent = ?"
                " AND verstr != parent LIMIT 1", (app, verstr)).fetchall())


def _decoded(conn, app, rows):
    """``{key: lean_row tuple}`` of *rows* in storage order."""
    ordered = sorted(rows.values(), key=lambda row: (row[2], row[0]))
    sides = lean_store._sides(
        side for chunk, marks in in_chunks(row[0] for row in ordered)
        for side in conn.execute(
            f"SELECT key, kind, data FROM exp_sides WHERE app = ? AND key IN ({marks})",
            (app, *chunk),
        )
    )
    return {key: lean_store._lean(lean_store.decode_row(idx, row), sides.get(key, {}))
            for key, idx, _, _, _, row in ordered}
