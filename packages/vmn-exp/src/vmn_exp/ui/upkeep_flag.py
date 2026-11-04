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

The flag's state and token come from the index refresher's listing of the
app where the store notes them (S3: ``children_flag_seen``), else from a
read: a flagged app costs a pass nothing, and a listed token predates the
pass's own listing as the conditional set needs.
"""
from collections import defaultdict

from vmn_exp.core.children import parent_of
from vmn_exp.core.children_scan import backfill_parent, flag_after_pass
from vmn_exp.storage.s3_base import parallel_map

MAX_UNSEEN = 100


def flag_marked_app(storage, app_name, snapshot):
    """Flag *app_name* complete after a pass marked every child in
    *snapshot*: True when flagged now, False when tried and not flagged
    (worth a backoff: it listed the app), None when nothing was tried."""
    if not storage.has_child_markers or snapshot.loading is not None:
        return None
    complete, token = _flag_state(storage, app_name)
    if complete or token is None:
        return None
    return flag_after_pass(storage, app_name,
                           lambda: _mark_listed(storage, app_name, snapshot), token)


def _flag_state(storage, app_name):
    """``(complete, token)`` of the flag: as the index refresher's listing
    (or this process's last write) showed it where the store tells
    (``children_flag_seen``), else read."""
    seen = getattr(storage, "children_flag_seen", None)
    state = seen(app_name) if seen else None
    return state if state is not None else storage.children_flag_state(app_name)


def _mark_listed(storage, app_name, snapshot):
    """List *app_name*'s run names and mark the children among (or of) the
    runs *snapshot* lacks; whether every one is marked."""
    names = list(storage.list_verstrs(app_name))
    unseen = [n for n in names if snapshot.row(n) is None]
    return len(unseen) <= MAX_UNSEEN and _mark_unseen(storage, app_name, snapshot, names, unseen)


def _mark_unseen(storage, app_name, snapshot, names, unseen):
    """Mark the children among (or of) *unseen* runs; whether none failed."""
    known, unseen_set = set(names), set(unseen)
    by_parent = defaultdict(list)
    metas = parallel_map(lambda v: storage.load_metadata(app_name, v), unseen)
    for verstr, meta in zip(unseen, metas):
        parent = parent_of(meta)
        if parent in known:
            by_parent[parent].append(verstr)
    for row in snapshot.rows:
        if row.get("parent") in unseen_set and parent_of(row):
            by_parent[row["parent"]].append(row["verstr"])
    counts = parallel_map(lambda p: backfill_parent(storage, app_name, p, by_parent[p], False),
                          list(by_parent))
    return not any(c["failed"] for c in counts)
