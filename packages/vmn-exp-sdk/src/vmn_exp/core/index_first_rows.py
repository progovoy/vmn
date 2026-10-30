#!/usr/bin/env python3
"""What a warm restart serves before it has read its persisted rows back:
the newest few and the trees around them, ``loading`` their share of every
persisted run.

Reading every persisted row back is O(runs) — at ~700k runs, minutes on a
server with nothing to show meanwhile. The newest rows come off the
persisted indexes alone (:mod:`~vmn_exp.core.index_lean_first`) with their
ancestors and the newest outer runs, numbered as the whole snapshot numbers
them, so a board or an Outer runs view opened meanwhile shows the recent
runs as they will stay.
"""
from dataclasses import replace

from vmn_exp.core.index_snapshot import (
    IndexSnapshot,
    _observed_at,
    new_side_tables,
    put_side_tables,
)


def first_rows(store, app_name, limit, max_rows):
    """An :class:`IndexSnapshot` (generation 0) of *store*'s *limit* newest
    persisted runs of *app_name* and the trees around them (at most
    *max_rows*), ``loading`` ``(rows, persisted runs)``;
    None when the store has none to serve (never saved, re-deriving,
    unavailable, or not a SQLite store)."""
    newest_of = getattr(store, "load_newest", None)
    newest = newest_of(app_name, limit, max_rows) if newest_of else None
    if not newest or not newest[1]:
        return None
    runs, lean, states = newest
    rows, notes, observed, run_states, sides = [], {}, {}, {}, new_side_tables()
    for key, (row, note, *values) in lean.items():
        verstr = row["verstr"]
        rows.append(row)
        notes[verstr] = note
        run_states[verstr] = states[key]["run_state"]
        observed[verstr] = _observed_at(states[key]["rs_sig"])
        put_side_tables(sides, verstr, values)
    snap = IndexSnapshot.build(app_name, 0, rows, run_states, notes, observed, **sides)
    return replace(snap, loading=(len(rows), runs))
