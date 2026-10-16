#!/usr/bin/env python3
"""Point reads on the persisted ``exp_rows`` (plan 25 §2, "point reads stay
point reads"): each answers through one of the table's indexes, never a scan
of the app.

:func:`resolve` answers exactly what
:meth:`~vmn_exp.core.index_snapshot.IndexSnapshot.resolve` answers over the
same rows — results and error strings alike.
"""
from vmn_exp.core.index_lean_store import decode_row
from vmn_exp.core.resolve_ref import RefLookups, resolve_with

_PREFIX_END = "\U0010ffff"  # sorts after any character a verstr carries


def resolve(conn, app, ref, latest=False, kind="experiment"):
    """``(verstr, error)`` for *ref* (see
    :func:`~vmn_exp.core.resolve_ref.resolve_with`), each lookup one indexed
    query."""
    return resolve_with(_lookups(conn, app), app, ref, latest, kind)


def _lookups(conn, app):
    def one(sql, *args):
        row = conn.execute(sql, (app, *args)).fetchone()
        return row[0] if row else None

    return RefLookups(
        latest=lambda: one(
            "SELECT verstr FROM exp_rows WHERE app = ? AND timestamp ="
            " (SELECT MAX(timestamp) FROM exp_rows WHERE app = ?) ORDER BY key LIMIT 1", app,
        ),
        at=lambda n: one("SELECT verstr FROM exp_rows WHERE app = ? AND idx = ?", n),
        count=lambda: one("SELECT COUNT(*) FROM exp_rows WHERE app = ?"),
        exists=lambda verstr: one(
            "SELECT 1 FROM exp_rows WHERE app = ? AND verstr = ?", verstr
        ) is not None,
        with_prefix=lambda prefix: [verstr for (verstr,) in conn.execute(
            "SELECT verstr FROM exp_rows WHERE app = ? AND verstr >= ? AND verstr < ?"
            " ORDER BY verstr", (app, prefix, prefix + _PREFIX_END),
        )],
    )


def row_of(conn, app, verstr):
    """*verstr*'s lean row with its ``idx``, or None."""
    found = conn.execute(
        "SELECT idx, row FROM exp_rows WHERE app = ? AND verstr = ?", (app, verstr)
    ).fetchone()
    if found is None:
        return None
    return decode_row(*found)


def parent_of(conn, app, verstr):
    found = conn.execute(
        "SELECT parent FROM exp_rows WHERE app = ? AND verstr = ?", (app, verstr)
    ).fetchone()
    return found[0] if found else None


def children_of(conn, app, verstr):
    """The runs whose parent is *verstr* (never itself), in storage order."""
    # "+idx": sort the parent index's few matches rather than walk the app in idx order.
    return [child for (child,) in conn.execute(
        "SELECT verstr FROM exp_rows WHERE app = ? AND parent = ? AND verstr != parent"
        " ORDER BY +idx", (app, verstr),
    )]
