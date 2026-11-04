#!/usr/bin/env python3
"""The store upkeep's (:mod:`~vmn_exp.ui.store_upkeep`) last step of a pass
that left every child of its snapshot marked: flag the app's markers
complete (:mod:`~vmn_exp.storage.children_flag`), so a ``prune -v`` of a
UI-served store never pays the one-time scan.

The snapshot was listed before the flag's token could be taken, so it alone
cannot prove a child created meanwhile is marked. The token is taken first,
then the app's run names are listed (names only, no record read): a run the
snapshot lacks has its ``metadata.yml`` read and, if it is a child, its
marker written — unless more than :data:`MAX_UNSEEN` are missing (the index
is still catching up; a later pass flags). The flag is then set on that
token, so a drop since — a child whose marker failed — keeps it unset.
"""
from collections import defaultdict

from vmn_exp.cli.backfill_children import backfill_parent, flag_token
from vmn_exp.core.children import parent_of

MAX_UNSEEN = 100


def flag_marked_app(storage, app_name, snapshot):
    """Flag *app_name* complete after a pass marked every child in
    *snapshot*; whether it was flagged now."""
    if not getattr(storage, "has_child_markers", False) or snapshot.loading is not None:
        return False
    if storage.children_complete(app_name):
        return False
    token = flag_token(storage, app_name)
    if token is None:
        return False
    names = list(storage.list_verstrs(app_name))
    unseen = [n for n in names if snapshot.row(n) is None]
    if len(unseen) > MAX_UNSEEN or not _mark_unseen(storage, app_name, snapshot, names, unseen):
        return False
    return storage.set_children_complete(app_name, True, since=token)


def _mark_unseen(storage, app_name, snapshot, names, unseen):
    """Mark the children among (or of) *unseen* runs; whether none failed."""
    known, unseen_set = set(names), set(unseen)
    by_parent = defaultdict(list)
    for verstr in unseen:
        parent = parent_of(storage.load_metadata(app_name, verstr))
        if parent in known:
            by_parent[parent].append(verstr)
    for row in snapshot.rows:
        if row.get("parent") in unseen_set and parent_of(row):
            by_parent[row["parent"]].append(row["verstr"])
    return not any(backfill_parent(storage, app_name, parent, kids, False)["failed"]
                   for parent, kids in by_parent.items())
