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
(exit 1) and the next backfill retries it. Prints ``wrote N, present M``
(and ``failed F``).
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
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        by_parent = _children_by_parent(storage, app_name, pool)
        results = pool.map(
            lambda p: _backfill_parent(storage, app_name, p, by_parent[p], dry_run),
            sorted(by_parent))
        results = list(results)
    return {key: sum(r[key] for r in results) for key in ("wrote", "present", "failed")}


def _children_by_parent(storage, app_name, pool):
    """``{parent: [child]}`` of the app's runs whose parent is one of them."""
    names = list(storage.list_verstrs(app_name))
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


def _backfill_parent(storage, app_name, parent, kids, dry_run):
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
