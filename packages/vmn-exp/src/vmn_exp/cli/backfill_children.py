#!/usr/bin/env python3
"""``vmn-exp backfill-children <app> [--dry-run]``: write the child markers
(:mod:`vmn_exp.storage.child_markers`) a store lacks — its runs predate them,
or a marker failed to write.

One pass over the app's index: every run whose ``parent`` is a run of the
app gets that parent's marker unless its listing (one per parent) already
holds it. A child of a run that is gone is left alone. Markers are written
directly, not best-effort, so a failure is counted (exit 1) and the next
backfill retries it. Prints ``wrote N, present M`` (and ``failed F``).
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core import index as experiment_index
from vmn_exp.core.tree import children_by_parent
from vmn_exp.storage.s3_base import parallel_map


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
    snap = experiment_index.indexed_snapshot(storage, app_name, wait=True)
    known = {row["verstr"] for row in snap.rows}
    by_parent = {p: kids for p, kids in children_by_parent(snap.rows).items() if p in known}
    each = parallel_map if storage.is_remote() else lambda fn, items: list(map(fn, items))
    results = each(lambda p: _backfill_parent(storage, app_name, p, by_parent[p], dry_run),
                   sorted(by_parent))
    return {key: sum(r[key] for r in results) for key in ("wrote", "present", "failed")}


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
