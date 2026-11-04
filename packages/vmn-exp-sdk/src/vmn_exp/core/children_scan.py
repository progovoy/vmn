#!/usr/bin/env python3
"""A pass over an app's runs that writes the child markers
(:mod:`vmn_exp.storage.child_markers`) a store lacks — and, when nothing
failed, flags the app's markers complete (:mod:`~vmn_exp.storage.children_flag`).

The flag is set by :func:`flag_after_pass`: the flag's token is taken
*before* the pass lists the app and the flag set only on it, so a drop that
landed meanwhile (a child the listing may have missed, whose marker failed)
keeps it unset. ``vmn-exp backfill-children``, the first ``prune -v`` of an
app and the UI's store upkeep all go through it.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.children import parent_of

WORKERS = 32


def flag_token(storage, app_name):
    """The completeness flag's token before a pass lists *app_name*; None
    (set nothing) when it cannot be read."""
    try:
        return storage.children_flag(app_name)
    except Exception:
        VMN_LOGGER.debug(f"Reading {app_name}'s child-marker flag failed", exc_info=True)
        return None


def flag_after_pass(storage, app_name, mark_fn, token=None):
    """Run *mark_fn* — a pass that lists *app_name* and marks its children,
    returning whether none failed — after taking the flag's token (unless
    *token* was taken already), then flag the app complete on that token if
    it passed; whether it was flagged."""
    if token is None:
        token = flag_token(storage, app_name)
    clean = mark_fn()
    if token is None or not clean:
        return False
    return storage.set_children_complete(app_name, True, since=token)


def scan_app(storage, app_name, dry_run=False, notice=None, on_read=None):
    """``(marker counts, {parent: [child]})`` of *app_name*'s runs, each
    child's missing marker written unless *dry_run*; a complete pass (not
    dry) flags the app (:func:`flag_after_pass`). *notice* is told the
    number of runs once they are listed, *on_read* called per run read."""
    found = []

    def mark():
        found.extend(_scan(storage, app_name, dry_run, notice, on_read))
        return not found[0]["failed"]

    if dry_run:
        mark()
    else:
        flag_after_pass(storage, app_name, mark)
    return found[0], found[1]


def _scan(storage, app_name, dry_run, notice, on_read):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        names = list(storage.list_verstrs(app_name))
        if notice:
            notice(len(names))
        by_parent = _children_by_parent(storage, app_name, names, pool, on_read)
        results = list(pool.map(
            lambda p: backfill_parent(storage, app_name, p, by_parent[p], dry_run),
            sorted(by_parent)))
    counts = {key: sum(r[key] for r in results) for key in ("wrote", "present", "failed")}
    return counts, by_parent


def _children_by_parent(storage, app_name, names, pool, on_read):
    """``{parent: [child]}`` of *names* (the app's runs) whose parent is one of them."""

    def read_parent(verstr):
        try:
            return parent_of(storage.load_metadata(app_name, verstr))
        finally:
            if on_read:
                on_read()

    known, by_parent = set(names), defaultdict(list)
    for verstr, parent in zip(names, pool.map(read_parent, names)):
        if parent in known:
            by_parent[parent].append(verstr)
    return by_parent


def backfill_parent(storage, app_name, parent, kids, dry_run):
    """``{"wrote", "present", "failed"}`` of *parent*'s *kids* markers: one
    listing of its markers, then each missing one written unless *dry_run*."""
    present = set(storage.list_children(app_name, parent))
    counts = {"wrote": 0, "present": 0, "failed": 0}
    for kid in kids:
        if kid in present:
            counts["present"] += 1
        elif dry_run or _mark(storage, app_name, parent, kid):
            counts["wrote"] += 1
        else:
            counts["failed"] += 1
    return counts


def _mark(storage, app_name, parent, kid):
    try:
        return storage.mark_child(app_name, parent, kid) is not False
    except Exception as exc:
        VMN_LOGGER.warning(f"Could not mark {kid} in {parent}: {exc}")
        return False
