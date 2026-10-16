#!/usr/bin/env python3
"""Point reads on the persisted ``exp_rows`` (plan 25 §2, "point reads stay
point reads"): each answers through one of the table's indexes, never a scan
of the app.

:func:`resolve` answers exactly what
:meth:`~vmn_exp.core.index_snapshot.IndexSnapshot.resolve` answers over the
same rows — results and error strings alike.
"""
import json

from vmn_exp.core.resolve_ref import AMBIGUOUS_REF, INVALID_REF, RefError

_LATEST_WORDS = ("latest", "@latest")
_PREFIX_END = "\U0010ffff"  # sorts after any character a verstr carries


def resolve(conn, app, ref, latest=False, kind="experiment"):
    """``(verstr, error)`` for *ref*: ``latest``/``@latest`` (or *latest*),
    ``@N``, an exact verstr, a unique dev-verstr prefix, or a stamped
    version passed through."""
    if latest or ref in _LATEST_WORDS:
        return _latest(conn, app, kind)
    if ref is None:
        return None, None
    if ref.startswith("@"):
        return _at_index(conn, app, ref)
    if "-dev." not in ref or _exists(conn, app, ref):
        return ref, None
    return _by_prefix(conn, app, ref, kind)


def _latest(conn, app, kind):
    row = conn.execute(
        "SELECT verstr FROM exp_rows WHERE app = ? AND timestamp ="
        " (SELECT MAX(timestamp) FROM exp_rows WHERE app = ?) ORDER BY key LIMIT 1",
        (app, app),
    ).fetchone()
    if row is None:
        return None, RefError(f"No {kind}s found for {app}")
    return row[0], None


def _at_index(conn, app, ref):
    idx = ref[1:]
    if not idx.isdigit():
        return None, RefError(f"Invalid index reference '{ref}' (use @N, e.g. @1)", INVALID_REF)
    row = conn.execute(
        "SELECT verstr FROM exp_rows WHERE app = ? AND idx = ?", (app, int(idx))
    ).fetchone()
    if row is not None and int(idx) >= 1:
        return row[0], None
    (count,) = conn.execute("SELECT COUNT(*) FROM exp_rows WHERE app = ?", (app,)).fetchone()
    return None, RefError(f"Index '{ref}' out of range (1..{count})")


def _exists(conn, app, verstr):
    return conn.execute(
        "SELECT 1 FROM exp_rows WHERE app = ? AND verstr = ?", (app, verstr)
    ).fetchone() is not None


def _by_prefix(conn, app, ref, kind):
    matches = [verstr for (verstr,) in conn.execute(
        "SELECT verstr FROM exp_rows WHERE app = ? AND verstr >= ? AND verstr < ?"
        " ORDER BY verstr", (app, ref, ref + _PREFIX_END),
    )]
    if len(matches) == 1:
        return matches[0], None
    if matches:
        return None, RefError(
            f"Ambiguous prefix '{ref}': matches {len(matches)} {kind}s: " + ", ".join(matches),
            AMBIGUOUS_REF,
        )
    return None, RefError(f"{kind.capitalize()} '{ref}' not found")


def row_of(conn, app, verstr):
    """*verstr*'s lean row with its ``idx``, or None."""
    found = conn.execute(
        "SELECT idx, row FROM exp_rows WHERE app = ? AND verstr = ?", (app, verstr)
    ).fetchone()
    if found is None:
        return None
    row = json.loads(found[1])
    row["idx"] = found[0]
    return row


def parent_of(conn, app, verstr):
    found = conn.execute(
        "SELECT parent FROM exp_rows WHERE app = ? AND verstr = ?", (app, verstr)
    ).fetchone()
    return found[0] if found else None


def children_of(conn, app, verstr):
    """The runs whose parent is *verstr* (never itself), in storage order."""
    return [child for (child,) in conn.execute(
        "SELECT verstr FROM exp_rows WHERE app = ? AND parent = ? AND verstr != parent"
        " ORDER BY idx", (app, verstr),
    )]
