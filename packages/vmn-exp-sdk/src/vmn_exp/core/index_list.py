#!/usr/bin/env python3
"""A listing of an app's runs answered from the persisted index without a
snapshot of the app (plan 25 §2): what ``vmn-exp list`` prints.

:func:`list_view` brings the persisted rows up to date with storage
(:meth:`~vmn_exp.core.index.ExperimentIndex.sync`), lets SQL pick the runs a
listing can keep (:func:`sql_filter`: the archived filter, ``--last N``
without a query, and a query's top-level ``status``/``parent``/``verstr``/
``name``/``archived`` clauses), then reads just those runs and their trees —
their ancestors (``depth``, ``root``, ``under()``) and everything beneath
them (``children``, ``tree_status``, ``child_counts``, sweep trials) — and
runs the same snapshot, annotation and query code over them as a full
listing does. So each run it answers is the one a full listing answers.

A stored ``status`` is the one derived when the record was last saved; only
the clock moves a run between ``running`` and ``stuck`` since, so a clause
on either keeps both, and every status is derived again from the run state.
"""
from vmn_exp.core import index_list_sql as sql
from vmn_exp.core import index as experiment_index
from vmn_exp.core.index_point import _store
from vmn_exp.core.index_rows import row_copies
from vmn_exp.core.index_snapshot import IndexSnapshot, _observed_at, new_side_tables
from vmn_exp.core.index_snapshot import put_side_tables
from vmn_exp.core.index_views import runs_declared_schema
from vmn_exp.core.log import filter_archived
from vmn_exp.core.query import filter_rows, parse_query
from vmn_exp.core.status import RUNNING, STUCK
from vmn_exp.core.tree import annotate_rows

_COLUMNS = ("status", "parent", "verstr", "name")
_CLOCKED = {RUNNING, STUCK}  # what the clock alone moves a run between


def sql_filter(query, archived):
    """``(where, params)``: SQL conditions on ``exp_rows`` every run that
    *query* (and, unless *archived*, the archived filter) keeps passes."""
    where, params = ([], []) if archived else (["archived = 0"], [])
    if query and query.strip():
        tree = parse_query(query)
        for clause in tree[1] if tree[0] == "and" else (tree,):
            _narrow(clause, where, params)
    return where, params


def _narrow(clause, where, params):
    if clause[0] == "cmp" and clause[2] == "=":
        field, values = clause[1], (clause[3],)
    elif clause[0] == "in":
        field, values = clause[1], clause[2]
    else:
        return
    column = field[1][0] if field[0] == "path" and len(field[1]) == 1 else None
    if column == "archived" and all(isinstance(v, bool) for v in values):
        where.append(f"archived IN ({', '.join('?' * len(values))})")
        params += [int(v) for v in values]
    if column not in _COLUMNS or not all(isinstance(v, str) for v in values):
        return
    values = set(values)
    if column == "status" and values & _CLOCKED:
        values |= _CLOCKED
    marks = ", ".join("?" * len(values))
    where.append(f"{column} IN ({marks})" + (" OR status IS NULL" if column == "status" else ""))
    params += sorted(values)


def list_view(storage, app_name, query=None, archived=False, last=None, schema=None):
    """``(rows, declared schema, app has runs)`` — *rows* the annotated runs
    *query* and the archived filter keep (the *last* ones without a query),
    in storage order, as a full listing builds them — or None when the
    persisted index cannot answer (the caller lists from a snapshot)."""
    path_of = getattr(storage, "index_cache_path", None)
    path = path_of(app_name) if path_of else None
    if not path or not experiment_index.shared_index(storage, app_name).sync():
        return None
    where, params = sql_filter(query, archived)
    has_query = bool(query and query.strip())
    parts = _store(path).listing(app_name, lambda conn: _read(
        conn, app_name, where, params, None if has_query else last))
    if parts is None:
        return None
    total, keep, found, declared = parts
    snap = _snapshot(app_name, found).summarized(schema)
    tree = annotate_rows(row_copies(snap, True), snap.run_states, snap.run_state_observed_at)
    rows = [row for row in filter_rows(tree, query) if row["verstr"] in keep]
    return filter_archived(rows, archived), runs_declared_schema(*declared), total > 0


def _read(conn, app, where, params, last):
    keep = sql.matching(conn, app, where, params, last)
    tree = _with_trees(conn, app, keep)
    found = sql.rows_of(conn, app, [key for key, _ in tree.values()])
    defs, rows = sql.declared(conn, app)
    return sql.count(conn, app), set(keep), found, (defs, rows.get)


def _with_trees(conn, app, keep):
    """*keep* (``{verstr: (key, parent)}``) with every run beneath them and
    their ancestors (cycle-safe: a run is taken once)."""
    have, frontier = dict(keep), list(keep)
    while frontier:
        below = {v: kp for v, kp in sql.children(conn, app, frontier).items() if v not in have}
        have.update(below)
        frontier = list(below)
    frontier = {parent for _, parent in keep.values() if parent and parent not in have}
    while frontier:
        above = sql.by_verstr(conn, app, frontier)
        have.update(above)
        frontier = {parent for _, parent in above.values() if parent and parent not in have}
    return have


def _snapshot(app_name, found):
    rows, notes, states, observed, sides = [], {}, {}, {}, new_side_tables()
    for row, note, values, state in found:
        verstr = row["verstr"]
        rows.append(row)
        notes[verstr] = note
        put_side_tables(sides, verstr, values)
        states[verstr] = state["run_state"]
        observed[verstr] = _observed_at(state["rs_sig"])
    return IndexSnapshot.build(app_name, 0, rows, states, notes, observed, **sides)
