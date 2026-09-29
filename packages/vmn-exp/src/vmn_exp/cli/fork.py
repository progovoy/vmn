#!/usr/bin/env python3
"""``vmn-exp create/run --fork-from <ref> [--fork-step N]`` and what ``show``
prints about fork origins and rewinds (see :mod:`vmn_exp.core.fork`)."""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.fork import resolve_run, seed_fork, split_fork_ref
from vmn_exp.core.rewind import rewinds_of


def fork_source(storage, app_name, args):
    """``((source verstr, step) or None, err)`` from ``--fork-from``/``--fork-step``,
    resolved before the new run is created so a bad ref creates nothing."""
    ref = getattr(args, "fork_from", None)
    step = getattr(args, "fork_step", None)
    if not ref:
        if step is not None:
            VMN_LOGGER.error("--fork-step needs --fork-from")
            return None, 1
        return None, None
    try:
        ref, step = split_fork_ref(ref, step)
        return (resolve_run(storage, app_name, ref, "fork"), step), None
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return None, 1


def seed(storage, app_name, verstr, source):
    """Seed the just-created *verstr* from *source* (a :func:`fork_source` result)."""
    if source is not None:
        seed_fork(storage, app_name, verstr, *source)


def print_lineage(metadata, log):
    """``show``'s rerun and fork origin and rewind lines."""
    if metadata.get("rerun_of"):
        print(f"  Rerun of: {metadata['rerun_of']}")
    origin = metadata.get("forked_from")
    if origin:
        print(f"  Forked from: {origin.get('verstr')} @ step {origin.get('step')}")
    for rewind in rewinds_of(log):
        print(f"  Rewound to step {rewind['step']} at {rewind['timestamp']}")
