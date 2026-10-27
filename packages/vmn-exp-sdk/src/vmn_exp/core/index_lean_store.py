#!/usr/bin/env python3
"""The lean tables of :class:`vmn_exp.core.index_store.SqliteStore`: what a
reader reads of each record, written in the record's own transaction (plan 25
§2, "persist what is read, not what is folded").

``exp_rows`` holds a run's :func:`~vmn_exp.core.index_views.lean_row` row
(its JSON, ``idx`` included but stale: the column is authoritative) beside the
columns a point read or ``list`` filters on: ``idx`` (the storage index, the
rank by ``(timestamp, key)`` — the index orders its records the same way),
``status`` (derived when the record or its run state was saved: a ``running``
run may read ``stuck`` since), ``parent``, ``root`` (its topmost ancestor, as
:func:`~vmn_exp.core.tree.ancestors` walks the parent links), ``timestamp``,
``name`` and ``archived``. ``exp_sides`` holds its create note and its
non-empty side table values (:data:`~vmn_exp.core.index_views.SIDE_TABLES`),
one row per ``kind``.

Only records with metadata and a fold get rows: the others are not runs.
"""
import json

from vmn_exp.core.index_lean_tree import fix_roots
from vmn_exp.core.index_snapshot import _observed_at
from vmn_exp.core.index_intern import compact_row
from vmn_exp.core.index_views import SIDE_TABLES, kept_side, lean_row
from vmn_exp.core.sqlite_conn import in_chunks
from vmn_exp.core.status import derive_status

NOTE = "create_note"


def _dumps(value):
    return json.dumps(value, default=str)


def decode_row(idx, text):
    """The lean row stored as *text*, its ``idx`` the column's *idx*, made
    of shared keys and values (:func:`~vmn_exp.core.index_intern.compact_row`)."""
    row = compact_row(json.loads(text))
    row["idx"] = idx
    return row


def sort_timestamp(meta):
    """The timestamp *meta* sorts by in storage order (``""`` unless a str)."""
    ts = meta.get("timestamp", "")
    return ts if isinstance(ts, str) else ""


def is_run(record):
    return record.get("meta") is not None and record.get("fold") is not None


def run_status(record):
    """*record*'s derived status, or None when its run state cannot say."""
    try:
        return derive_status(record.get("run_state"),
                             observed_at=_observed_at(record.get("rs_sig")))
    except (TypeError, ValueError):  # a hand-edited, unparseable exit code
        return None


def leans_of(records):
    """``{key: lean_row tuple}`` of the runs among *records* (``idx`` 0)."""
    return {key: lean_row(0, record["meta"], record["fold"])
            for key, record in records.items() if is_run(record)}


def write_lean(conn, app, seq, changed, removed, states, leans, renumber=True):
    """Bring *app*'s lean tables in line with a save of *changed* records
    (*leans* their runs' :func:`leans_of`), *removed* keys and the run states
    of *states* (see :meth:`~vmn_exp.core.index_store.SqliteStore.save`);
    whether every row's ``idx`` is its rank now. Without *renumber* a save
    that would renumber the app leaves its new rows' ``idx`` unset instead
    (:func:`renumber_all` later)."""
    runs = {key: changed[key] for key in leans}
    gone = set(removed) | {key for key in changed if key not in runs}
    before = _existing(conn, app, sorted(set(runs) | gone))
    _delete(conn, app, gone)
    _upsert(conn, app, seq, runs, leans)
    conn.executemany(
        "UPDATE exp_rows SET status = ? WHERE app = ? AND key = ?",
        [(run_status(r), app, key) for key, r in states.items() if key not in runs],
    )
    numbered = _renumber(conn, app, runs, gone, before, renumber)
    moved = [key for key, record in runs.items()
             if before.get(key, (None, None, None))[1:] != (
                 record["meta"].get("parent"), record["meta"]["verstr"])]
    fix_roots(conn, app, [runs[key]["meta"]["verstr"] for key in moved]
              + [before[key][2] for key in gone if key in before])
    return numbered


def _existing(conn, app, keys):
    """``{key: (timestamp, parent, verstr)}`` of *keys*' current rows."""
    out = {}
    for chunk, marks in in_chunks(keys):
        out.update((key, (ts, parent, verstr)) for key, ts, parent, verstr in conn.execute(
            "SELECT key, timestamp, parent, verstr FROM exp_rows WHERE app = ?"
            f" AND key IN ({marks})", (app, *chunk),
        ))
    return out


def _delete(conn, app, keys):
    gone = [(app, key) for key in keys]
    conn.executemany("DELETE FROM exp_rows WHERE app = ? AND key = ?", gone)
    conn.executemany("DELETE FROM exp_sides WHERE app = ? AND key = ?", gone)


def _upsert(conn, app, seq, runs, leans):
    rows, sides = [], []
    for key, record in runs.items():
        meta = record["meta"]
        row, note, *values = leans[key]
        rows.append((
            app, key, meta["verstr"], run_status(record), row.get("parent"),
            sort_timestamp(meta), row.get("name"), int(row["archived"]), seq, _dumps(row),
        ))
        if note is not None:
            sides.append((app, key, NOTE, _dumps(note)))
        sides += [(app, key, kind, _dumps(v)) for kind, v in zip(SIDE_TABLES, values) if v]
    conn.executemany(
        "INSERT INTO exp_rows (app, key, verstr, status, parent, timestamp, name,"
        " archived, seq, row) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (app, key) DO UPDATE SET verstr = excluded.verstr,"
        " status = excluded.status, parent = excluded.parent,"
        " timestamp = excluded.timestamp, name = excluded.name,"
        " archived = excluded.archived, seq = excluded.seq, row = excluded.row",
        rows,
    )
    conn.executemany(
        "DELETE FROM exp_sides WHERE app = ? AND key = ?", [(app, key) for key in runs]
    )
    conn.executemany(
        "INSERT INTO exp_sides (app, key, kind, data) VALUES (?, ?, ?, ?)", sides
    )


def _renumber(conn, app, runs, gone, before, renumber=True):
    """Keep ``idx`` the rank by ``(timestamp, key)``: new runs sorting after
    every other row are numbered on; any other move renumbers the app — or,
    without *renumber*, leaves it to :func:`renumber_all` (False)."""
    new = [key for key in runs if key not in before]
    redescribed = any(
        before[key][0] != sort_timestamp(runs[key]["meta"]) for key in runs if key in before
    )
    reshuffled = redescribed or any(key in before for key in gone)
    if not new and not reshuffled:
        return True
    if not reshuffled and _number_on(
        conn, app, sorted((sort_timestamp(runs[k]["meta"]), k) for k in new)
    ):
        return True
    if not renumber:
        return False
    renumber_all(conn, app)
    return True


def renumber_all(conn, app):
    """Make every row's ``idx`` its rank by ``(timestamp, key)``."""
    ranked = conn.execute(
        "SELECT key, idx FROM exp_rows WHERE app = ? ORDER BY timestamp, key", (app,)
    ).fetchall()
    conn.executemany(
        "UPDATE exp_rows SET idx = ? WHERE app = ? AND key = ?",
        [(n, app, key) for n, (key, idx) in enumerate(ranked, 1) if idx != n],
    )


def _number_on(conn, app, new):
    """Number *new* (``[(timestamp, key)]``, sorted) after the numbered rows
    when they all sort after them; False when one does not, or when other
    rows are unnumbered (a save that left them to :func:`renumber_all`)."""
    last = conn.execute(
        "SELECT timestamp, key, idx FROM exp_rows WHERE app = ? AND idx IS NOT NULL"
        " ORDER BY timestamp DESC, key DESC LIMIT 1", (app,)
    ).fetchone()
    (numbered,) = conn.execute(
        "SELECT COUNT(*) FROM exp_rows WHERE app = ? AND idx IS NOT NULL", (app,)
    ).fetchone()
    (unnumbered,) = conn.execute(
        "SELECT COUNT(*) FROM exp_rows WHERE app = ? AND idx IS NULL", (app,)
    ).fetchone()
    if unnumbered != len(new):
        return False
    if last is not None and (new[0] <= (last[0], last[1]) or last[2] != numbered):
        return False
    conn.executemany(
        "UPDATE exp_rows SET idx = ? WHERE app = ? AND key = ?",
        [(numbered + n, app, key) for n, (_, key) in enumerate(new, 1)],
    )
    return True


def read_lean(conn, app):
    """``(keys, {key: lean_row tuple}, stamps)`` of *app*'s runs in storage
    order, each row's ``idx`` its place in it; *stamps* their ``(timestamp,
    key)`` sort keys."""
    sides = {}
    for key, kind, data in conn.execute(
        "SELECT key, kind, data FROM exp_sides WHERE app = ?", (app,)
    ):
        sides.setdefault(key, {})[kind] = kept_side(kind, json.loads(data))
    keys, lean, stamps = [], {}, []
    for n, (key, ts, row) in enumerate(conn.execute(
        "SELECT key, timestamp, row FROM exp_rows WHERE app = ? ORDER BY timestamp, key",
        (app,),
    ), 1):
        row = decode_row(n, row)
        own = sides.get(key, {})
        keys.append(key)
        stamps.append((ts, key))
        lean[key] = (row, own.get(NOTE), *(own.get(kind) for kind in SIDE_TABLES))
    return keys, lean, stamps
