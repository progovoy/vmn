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
from vmn_exp.core.index_views import SIDE_TABLES, lean_row
from vmn_exp.core.status import derive_status, observed_at_from_mtime

NOTE = "create_note"
_KEYS_PER_QUERY = 500


def _dumps(value):
    return json.dumps(value, default=str)


def _timestamp(meta):
    ts = meta.get("timestamp", "")
    return ts if isinstance(ts, str) else ""


def is_run(record):
    return record.get("meta") is not None and record.get("fold") is not None


def run_status(record):
    """*record*'s derived status, or None when its run state cannot say."""
    rs_sig = record.get("rs_sig")
    observed = observed_at_from_mtime(rs_sig[1]) if rs_sig and len(rs_sig) > 1 else None
    try:
        return derive_status(record.get("run_state"), observed_at=observed)
    except (TypeError, ValueError):  # a hand-edited, unparseable exit code
        return None


def write_lean(conn, app, seq, changed, removed, states):
    """Bring *app*'s lean tables in line with a save of *changed* records,
    *removed* keys and the run states of *states* (see
    :meth:`~vmn_exp.core.index_store.SqliteStore.save`)."""
    runs = {key: record for key, record in changed.items() if is_run(record)}
    gone = set(removed) | {key for key in changed if key not in runs}
    before = _existing(conn, app, sorted(set(runs) | gone))
    _delete(conn, app, gone)
    _upsert(conn, app, seq, runs)
    conn.executemany(
        "UPDATE exp_rows SET status = ? WHERE app = ? AND key = ?",
        [(run_status(r), app, key) for key, r in states.items() if key not in runs],
    )
    _renumber(conn, app, runs, gone, before)
    moved = [key for key, record in runs.items()
             if before.get(key, (None, None, None))[1:] != (
                 record["meta"].get("parent"), record["meta"]["verstr"])]
    fix_roots(conn, app, [runs[key]["meta"]["verstr"] for key in moved]
              + [before[key][2] for key in gone if key in before])


def _existing(conn, app, keys):
    """``{key: (timestamp, parent, verstr)}`` of *keys*' current rows."""
    out = {}
    for i in range(0, len(keys), _KEYS_PER_QUERY):
        chunk = keys[i:i + _KEYS_PER_QUERY]
        out.update((key, (ts, parent, verstr)) for key, ts, parent, verstr in conn.execute(
            "SELECT key, timestamp, parent, verstr FROM exp_rows WHERE app = ?"
            f" AND key IN ({', '.join('?' * len(chunk))})", (app, *chunk),
        ))
    return out


def _delete(conn, app, keys):
    gone = [(app, key) for key in keys]
    conn.executemany("DELETE FROM exp_rows WHERE app = ? AND key = ?", gone)
    conn.executemany("DELETE FROM exp_sides WHERE app = ? AND key = ?", gone)


def _upsert(conn, app, seq, runs):
    rows, sides = [], []
    for key, record in runs.items():
        meta = record["meta"]
        row, note, *values = lean_row(0, meta, record["fold"])
        rows.append((
            app, key, meta["verstr"], run_status(record), row.get("parent"),
            _timestamp(meta), row.get("name"), int(row["archived"]), seq, _dumps(row),
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


def _renumber(conn, app, runs, gone, before):
    """Keep ``idx`` the rank by ``(timestamp, key)``: new runs sorting after
    every other row are numbered on; any other move renumbers the app."""
    new = [key for key in runs if key not in before]
    redescribed = any(
        before[key][0] != _timestamp(runs[key]["meta"]) for key in runs if key in before
    )
    if not new and not redescribed and not any(key in before for key in gone):
        return
    if not redescribed and not any(key in before for key in gone):
        if _number_on(conn, app, sorted((_timestamp(runs[k]["meta"]), k) for k in new)):
            return
    ranked = conn.execute(
        "SELECT key, idx FROM exp_rows WHERE app = ? ORDER BY timestamp, key", (app,)
    ).fetchall()
    conn.executemany(
        "UPDATE exp_rows SET idx = ? WHERE app = ? AND key = ?",
        [(n, app, key) for n, (key, idx) in enumerate(ranked, 1) if idx != n],
    )


def _number_on(conn, app, new):
    """Number *new* (``[(timestamp, key)]``, sorted) after the numbered rows
    when they all sort after them; False when one does not."""
    last = conn.execute(
        "SELECT timestamp, key, idx FROM exp_rows WHERE app = ? AND idx IS NOT NULL"
        " ORDER BY timestamp DESC, key DESC LIMIT 1", (app,)
    ).fetchone()
    (numbered,) = conn.execute(
        "SELECT COUNT(*) FROM exp_rows WHERE app = ? AND idx IS NOT NULL", (app,)
    ).fetchone()
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
        sides.setdefault(key, {})[kind] = json.loads(data)
    keys, lean, stamps = [], {}, []
    for n, (key, ts, row) in enumerate(conn.execute(
        "SELECT key, timestamp, row FROM exp_rows WHERE app = ? ORDER BY timestamp, key",
        (app,),
    ), 1):
        row = json.loads(row)
        row["idx"] = n
        own = sides.get(key, {})
        keys.append(key)
        stamps.append((ts, key))
        lean[key] = (row, own.get(NOTE), *(own.get(kind) for kind in SIDE_TABLES))
    return keys, lean, stamps
