#!/usr/bin/env python3
"""The ``root`` column of ``exp_rows``: each run's topmost ancestor, walked
over the persisted parent links exactly as :func:`~vmn_exp.core.tree.ancestors`
walks them (a missing parent ends the chain and is its root; a cycle stops
at its entry point; a top-level run has none).

A save re-derives the roots of the runs whose parent link appeared, moved or
went, and of everything below them — a few point queries per run. A bulk
save (a cold build) re-derives the whole app from one scan instead.
"""
from vmn_exp.core.tree import ancestors

_BULK = 500  # changed runs past which one scan beats point queries


def fix_roots(conn, app, verstrs):
    """Re-derive the roots of *verstrs* and of every run below them."""
    if not verstrs:
        return
    if len(verstrs) > _BULK:
        _fix_all(conn, app)
        return
    links = _Links(conn, app)
    updates = []
    for verstr in links.below(verstrs):
        root = links.root(verstr)
        if root != links.stored_root(verstr):
            updates.append((root, app, verstr))
    conn.executemany("UPDATE exp_rows SET root = ? WHERE app = ? AND verstr = ?", updates)


def _fix_all(conn, app):
    rows = conn.execute(
        "SELECT verstr, parent, root FROM exp_rows WHERE app = ?", (app,)
    ).fetchall()
    parent_of = {verstr: parent for verstr, parent, _ in rows if parent}
    updates = []
    for verstr, _, stored in rows:
        chain = ancestors(verstr, parent_of)
        root = chain[-1] if chain else None
        if root != stored:
            updates.append((root, app, verstr))
    conn.executemany("UPDATE exp_rows SET root = ? WHERE app = ? AND verstr = ?", updates)


class _Links:
    """Parent links read on demand through the ``(app, verstr)`` and
    ``(app, parent)`` indexes."""

    def __init__(self, conn, app):
        self._conn, self._app = conn, app
        self._rows = {}  # verstr -> (parent, root) or None

    def _row(self, verstr):
        if verstr not in self._rows:
            self._rows[verstr] = self._conn.execute(
                "SELECT parent, root FROM exp_rows WHERE app = ? AND verstr = ?",
                (self._app, verstr),
            ).fetchone()
        return self._rows[verstr]

    def get(self, verstr, default=None):
        row = self._row(verstr)
        return (row[0] if row else None) or default

    def stored_root(self, verstr):
        return self._row(verstr)[1]

    def root(self, verstr):
        chain = ancestors(verstr, self)
        return chain[-1] if chain else None

    def below(self, verstrs):
        """The present runs among *verstrs* and every run under them."""
        seen, stack, out = set(), list(verstrs), []
        while stack:
            verstr = stack.pop()
            if verstr in seen:
                continue
            seen.add(verstr)
            if self._row(verstr) is not None:
                out.append(verstr)
            stack.extend(child for (child,) in self._conn.execute(
                "SELECT verstr FROM exp_rows WHERE app = ? AND parent = ?",
                (self._app, verstr),
            ))
        return out
