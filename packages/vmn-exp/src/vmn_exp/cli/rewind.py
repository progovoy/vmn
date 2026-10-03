#!/usr/bin/env python3
"""``vmn-exp rewind <app> -v <ref> --step N``: hide a run's history past step N.

The CLI counterpart of ``start_run(run_id=<ref>, rewind_to_step=N)`` for a
run that is not reopened: it appends the same ``rewind`` marker (see
:func:`vmn_exp.core.fork.rewind_run`) and is refused while the run is running.
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.fork import resolve_run, rewind_run
from vmn_exp.core.metric_compact import rebuild_compacted
from vmn_exp.core.rewind import count_hidden
from vmn_exp.core.status import load_run_state
from vmn_exp.core.writer import flush_log


def _ref(args):
    versions = getattr(args, "version", None)
    if versions:
        return versions[0]
    return "latest" if getattr(args, "latest", False) else None


def experiment_rewind(storage, app_name, args):
    ref, step = _ref(args), getattr(args, "step", None)
    if ref is None or step is None:
        VMN_LOGGER.error("exp rewind needs a run (-v or --latest) and --step N")
        return 1
    try:
        verstr = resolve_run(storage, app_name, ref, "rewind")
        hidden = count_hidden(storage.load_merged_log(app_name, verstr), step)
        rewind_run(storage, app_name, verstr, step,
                   load_run_state(storage, app_name, verstr) or {})
    except (ValueError, RuntimeError) as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    # One-shot command: no heartbeat will ship the marker to a remote later.
    flush_log(storage, app_name, verstr)
    rebuild_compacted(storage, app_name, verstr)
    print(f"rewound {verstr} to step {step} (hid {hidden} entries)")
    return 0
