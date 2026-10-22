#!/usr/bin/env python3
"""A point placement (see :func:`vmn_exp.core.refs.point_placement`) of one
run read straight from storage: for a host without a persisted index, where
the only other placement lists every run of the app.

It holds the run's subtree (:func:`~vmn_exp.core.subtree_direct.subtree_rows_direct`,
through child markers) and its ancestors (one ``metadata.yml`` each), so a
run's row, ``depth`` and ``tree_status`` cost its own tree. Rows have no
``idx`` (the storage index needs the full listing), and a child without a
marker (``vmn-exp backfill-children``) is missed.
"""
from vmn_exp.core.fold import new_fold
from vmn_exp.core.index_views import lean_row
from vmn_exp.core.subtree_direct import subtree_rows_direct
from vmn_exp.core.tree import children_by_parent


class DirectPlacement:
    def __init__(self, rows):
        self._rows = {row["verstr"]: row for row in rows}
        self.parent_of = {row["verstr"]: row.get("parent") for row in rows}
        self.children_of = children_by_parent(rows)

    def row(self, verstr):
        return self._rows.get(verstr)


def direct_placement(storage, app_name, verstr):
    """*verstr*'s :class:`DirectPlacement`, or None when it does not exist."""
    rows = list(subtree_rows_direct(storage, app_name, verstr).rows)
    if not rows:
        return None
    seen, parent = {verstr}, rows[0].get("parent")
    while parent and parent not in seen:
        seen.add(parent)
        meta = storage.load_metadata(app_name, parent)
        if meta is None:
            break
        rows.append(lean_row(None, meta, new_fold())[0])
        parent = meta.get("parent")
    return DirectPlacement(rows)
