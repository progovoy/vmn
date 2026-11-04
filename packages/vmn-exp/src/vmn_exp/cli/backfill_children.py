#!/usr/bin/env python3
"""``vmn-exp backfill-children <app> [--dry-run]``: write the child markers
(:mod:`vmn_exp.storage.child_markers`) a store lacks — its runs predate them,
or a marker failed to write.

One listing of the app's run names, then each run's ``metadata.yml`` alone
(:data:`~vmn_exp.core.children_scan.WORKERS` at a time, progress on stderr) — never the index, whose
cold load also reads every run's state and logs. Every run whose ``parent``
is a run of the app gets that parent's marker unless its listing (one per
parent) already holds it. A child of a run that is gone is left alone.
Markers are written directly, not best-effort, so a failure is counted
(exit 1) and the next backfill retries it. A pass with no failure flags the
app's markers complete (:mod:`vmn_exp.core.children_scan`). Prints ``wrote N,
present M`` (and ``failed F``).

Optional: the first ``vmn-exp prune -v`` of an app not flagged complete runs
the same pass itself (:mod:`vmn_exp.cli.prune_targeted`).
"""
import sys
import threading

from vmn_exp.core import children_scan

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
    """:func:`vmn_exp.core.children_scan.scan_app`, its reads' progress on
    stderr. *notice* is told the number of runs once they are listed."""
    progress = _Progress()

    def listed(total):
        progress.total = total
        if notice:
            notice(total)

    return children_scan.scan_app(storage, app_name, dry_run, listed, progress.tick)


class _Progress:
    def __init__(self):
        self.total, self.done, self._lock = 0, 0, threading.Lock()

    def tick(self):
        with self._lock:
            self.done += 1
            if self.done % PROGRESS_EVERY == 0 or self.done == self.total:
                print(f"read {self.done}/{self.total} runs", file=sys.stderr, flush=True)
