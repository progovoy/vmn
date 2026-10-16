#!/usr/bin/env python3
"""The reads behind a listing answered from the persisted ``exp_rows`` (plan
25 §2; :mod:`vmn_exp.core.index_list`): which runs a filter keeps, their
trees' links, and the rows of just those runs — each through one of the
table's indexes, a chunk of keys per query.

Rows come back as a snapshot holds them (:func:`rows_of`): the lean row with
its ``idx``, create note, side table values
(:data:`~vmn_exp.core.index_views.SIDE_TABLES`) and run state fields.
"""
import json

from vmn_exp.core.index_lean_store import NOTE
from vmn_exp.core.index_views import SIDE_TABLES

_CHUNK = 500  # keys per query, under SQLite's bound-parameter limit
_NO_STATE = {"rs_sig": None, "run_state": None}


def _chunks(values):
    values = list(values)
    for i in range(0, len(values), _CHUNK):
        chunk = values[i:i + _CHUNK]
        yield chunk, ", ".join("?" * len(chunk))


def count(conn, app):
    (n,) = conn.execute("SELECT COUNT(*) FROM exp_rows WHERE app = ?", (app,)).fetchone()
    return n


def matching(conn, app, where, params, last=None):
    """``{verstr: (key, parent)}`` of the runs every SQL condition of *where*
    (with *params*) keeps — the *last* ones in storage order when given."""
    sql = "SELECT verstr, key, parent FROM exp_rows WHERE app = ?"
    sql += "".join(f" AND ({w})" for w in where)
    args = [app, *params]
    if last:
        sql += " ORDER BY idx DESC LIMIT ?"
        args.append(last)
    return {verstr: (key, parent) for verstr, key, parent in conn.execute(sql, args)}


def by_verstr(conn, app, verstrs):
    """``{verstr: (key, parent)}`` of those of *verstrs* that are runs."""
    out = {}
    for chunk, marks in _chunks(verstrs):
        out.update((v, (k, p)) for v, k, p in conn.execute(
            f"SELECT verstr, key, parent FROM exp_rows WHERE app = ? AND verstr IN ({marks})",
            (app, *chunk),
        ))
    return out


def children(conn, app, verstrs):
    """``{verstr: (key, parent)}`` of the runs whose parent is one of *verstrs*."""
    out = {}
    for chunk, marks in _chunks(verstrs):
        out.update((v, (k, p)) for v, k, p in conn.execute(
            f"SELECT verstr, key, parent FROM exp_rows WHERE app = ? AND parent IN ({marks})"
            " AND verstr != parent", (app, *chunk),
        ))
    return out


def rows_of(conn, app, keys):
    """``[(row, create note, side values, run state fields)]`` of *keys*'
    runs in storage order, each row's ``idx`` its column's."""
    keys = list(keys)
    found, sides, states = [], {}, {}
    for chunk, marks in _chunks(keys):
        args = (app, *chunk)
        found += conn.execute(
            f"SELECT key, idx, row FROM exp_rows WHERE app = ? AND key IN ({marks})", args
        ).fetchall()
        for key, kind, data in conn.execute(
            f"SELECT key, kind, data FROM exp_sides WHERE app = ? AND key IN ({marks})", args
        ):
            sides.setdefault(key, {})[kind] = json.loads(data)
        states.update(conn.execute(
            f"SELECT key, data FROM exp_index_state WHERE app = ? AND key IN ({marks})", args
        ))
    out = []
    for key, idx, row in sorted(found, key=lambda found_row: found_row[1]):
        row = dict(json.loads(row), idx=idx)
        own = sides.get(key, {})
        state = dict(_NO_STATE, **json.loads(states[key])) if key in states else _NO_STATE
        out.append((row, own.get(NOTE), [own.get(kind) for kind in SIDE_TABLES], state))
    return out


def declared(conn, app):
    """``({verstr: declared}, {verstr: row})`` of the runs declaring a metric
    goal or visibility — what the app's declared schema merges, the runs
    oldest first by their row."""
    defs, rows = {}, {}
    for verstr, idx, row, data in conn.execute(
        "SELECT r.verstr, r.idx, r.row, s.data FROM exp_sides s JOIN exp_rows r"
        " ON r.app = s.app AND r.key = s.key WHERE s.app = ? AND s.kind = 'declared_defs'",
        (app,),
    ):
        defs[verstr] = json.loads(data)
        rows[verstr] = dict(json.loads(row), idx=idx)
    return defs, rows
