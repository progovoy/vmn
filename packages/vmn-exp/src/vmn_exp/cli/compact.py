#!/usr/bin/env python3
"""``vmn-exp compact <app> [-v <ref>...] [--all-finished]``: build the
``metrics/<w>.vmx`` of writers that died before compacting (plan 12 §6).

Running runs are never compacted: their writer still appends to the stream.
``vmn-exp watch --compact`` calls :func:`compact_runs` on failed/stuck runs.
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core import index as experiment_index
from vmn_exp.core.fork import resolve_run
from vmn_exp.core.metric_compact import compact_record
from vmn_exp.core.status import FAILED, RUNNING, STUCK, SUCCEEDED, derive_status

FINISHED = (SUCCEEDED, FAILED)
DEAD = (FAILED, STUCK)


def runs_with_status(storage, app_name, statuses):
    """The verstrs of *app_name*'s runs whose derived status is in *statuses*."""
    snap = experiment_index.indexed_snapshot(storage, app_name, wait=True)
    return sorted(v for v, state in snap.run_states.items()
                  if derive_status(state, observed_at=snap.run_state_observed_at.get(v))
                  in statuses)


def compact_runs(storage, app_name, verstrs):
    """Compact each run, printing ``<verstr> compacted (N writers)`` or
    ``<verstr> up-to-date``; the number that failed."""
    failed = 0
    for verstr in verstrs:
        try:
            writers = compact_record(storage, app_name, verstr)
        except Exception as exc:
            VMN_LOGGER.error(f"{verstr}: compaction failed: {exc}")
            failed += 1
            continue
        n = len(writers)
        print(f"{verstr} compacted ({n} writer{'' if n == 1 else 's'})" if n
              else f"{verstr} up-to-date")
    return failed


def _named_runs(storage, app_name, refs):
    live = set(runs_with_status(storage, app_name, (RUNNING,)))
    verstrs = [resolve_run(storage, app_name, ref, "compact") for ref in refs]
    running = [v for v in verstrs if v in live]
    if running:
        raise ValueError(f"Run '{running[0]}' is running; it compacts itself at its end.")
    return verstrs


def experiment_compact(storage, app_name, args):
    refs = getattr(args, "version", None) or []
    if bool(refs) == bool(getattr(args, "all_finished", False)):
        VMN_LOGGER.error("exp compact needs run refs (-v) or --all-finished, not both")
        return 1
    try:
        verstrs = (_named_runs(storage, app_name, refs) if refs
                   else runs_with_status(storage, app_name, FINISHED))
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    return 1 if compact_runs(storage, app_name, verstrs) else 0
