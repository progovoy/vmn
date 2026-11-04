#!/usr/bin/env python3
"""``vmn-exp backfill-children <app> [--dry-run]``: write the child markers
(:mod:`vmn_exp.storage.child_markers`) a store lacks — its runs predate them,
or a marker failed to write.

One listing of the app's run names, then each run's ``metadata.yml`` alone
(:data:`WORKERS` at a time, progress on stderr) — never the index, whose
cold load also reads every run's state and logs. Every run whose ``parent``
is a run of the app gets that parent's marker unless its listing (one per
parent) already holds it. A child of a run that is gone is left alone.
Markers are written directly, not best-effort, so a failure is counted
(exit 1) and the next backfill retries it. A pass with no failure flags the
app's markers complete (``set_children_complete``). Prints ``wrote N,
present M`` (and ``failed F``).

Optional: the first ``vmn-exp prune -v`` of an app not flagged complete runs
the same pass itself (:mod:`vmn_exp.cli.prune_targeted`).
"""
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.children import parent_of

WORKERS = 32
PROGRESS_EVERY = 1000


def experiment_backfill_children(storage, app_name, args):
    dry_run = bool(getattr(args, "dry_run", False))
    counts = backfill_app(storage, app_name, dry_run)
    summary = f"wrote {counts['wrote']}, present {counts['present']}"
    if counts["failed"]:
        summary += f", failed {counts['failed']}"
    print(summary + (" (dry run: nothing written)" if dry_run else ""))
    return 1 if counts["failed"] else 0


def backfill_app(storage, app_name, dry_run=False):
    """``{"wrote", "present", "failed"}`` marker counts of *app_name*'s runs."""
    return scan_app(storage, app_name, dry_run)[0]


def scan_app(storage, app_name, dry_run=False, notice=None):
    """``(marker counts, {parent: [child]})`` of *app_name*'s runs, each
    child's missing marker written unless *dry_run*. A complete pass (not
    dry, nothing failed) flags the app's markers complete — conditionally,
    on the flag's token taken before the listing, so a drop that landed
    meanwhile (a child the listing may have missed) keeps it unset.
    *notice* is told the number of runs once they are listed."""
    token = None if dry_run else flag_token(storage, app_name)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        names = list(storage.list_verstrs(app_name))
        if notice:
            notice(len(names))
        by_parent = _children_by_parent(storage, app_name, names, pool)
        results = list(pool.map(
            lambda p: backfill_parent(storage, app_name, p, by_parent[p], dry_run),
            sorted(by_parent)))
    counts = {key: sum(r[key] for r in results) for key in ("wrote", "present", "failed")}
    if token is not None and not counts["failed"]:
        storage.set_children_complete(app_name, True, since=token)
    return counts, by_parent


def flag_token(storage, app_name):
    """The completeness flag's token before a pass lists *app_name*; None
    (set nothing) when it cannot be read."""
    try:
        return storage.children_flag(app_name)
    except Exception:
        VMN_LOGGER.debug(f"Reading {app_name}'s child-marker flag failed", exc_info=True)
        return None


def _children_by_parent(storage, app_name, names, pool):
    """``{parent: [child]}`` of *names* (the app's runs) whose parent is one of them."""
    progress = _Progress(len(names))

    def read_parent(verstr):
        try:
            return parent_of(storage.load_metadata(app_name, verstr))
        finally:
            progress.tick()

    known, by_parent = set(names), defaultdict(list)
    for verstr, parent in zip(names, pool.map(read_parent, names)):
        if parent in known:
            by_parent[parent].append(verstr)
    return by_parent


class _Progress:
    def __init__(self, total):
        self.total, self.done, self._lock = total, 0, threading.Lock()

    def tick(self):
        with self._lock:
            self.done += 1
            if self.done % PROGRESS_EVERY == 0 or self.done == self.total:
                print(f"read {self.done}/{self.total} runs", file=sys.stderr, flush=True)


def backfill_parent(storage, app_name, parent, kids, dry_run):
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
