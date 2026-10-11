"""The submission hint: once ``vmn-exp create``/``run`` claimed a run, the past
runs most like it, on stderr — before ``run`` starts the child::

    2 similar runs: best val_loss=0.31 — <verstr> by alice@x.io, 3w ago (<reasons>)
      <verstr> by bob@x.io, 2d ago (<reasons>)

Cheap or nothing. It reads the app's persisted index cache only when one
exists — a cold cache would mean reading every record — and prints nothing
past :data:`BUDGET_SEC` (the search runs on a daemon thread that is then left
to finish unused). It is never computed for inner runs (``--parent``, an
enclosing run's ``VMN_EXPERIMENT_ID``, sweep trials), with ``--no-similar``
or with conf ``experiment.similar.hint: false``. Errors are logged at debug
and never touch the run. ``vmn-exp similar <app> -v <verstr>`` shows the rest.
"""
import os
import sys
import threading
import time

from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.similar_output import hint_lines
from vmn_exp.core.index import indexed_snapshot
from vmn_exp.core.similar_search import (
    conf_schema,
    conf_weights,
    hint_enabled,
    run_target,
    search,
)

BUDGET_SEC = 0.3
HINT_TOP = 3
# Set in an enclosing run's children (VMN_EXPERIMENT_ID) and in sweep trials.
INNER_RUN_ENVS = ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL")
_clock = time.monotonic


def print_hint(storage, app_name, verstr, args, exp_conf):
    """Print the hint for the new run *verstr*, when wanted and cheap."""
    try:
        if not _wanted(args, exp_conf) or not index_is_warm(storage, app_name):
            return
        lines = _within_budget(lambda: _lines(storage, app_name, verstr, exp_conf))
    except Exception:
        VMN_LOGGER.debug("No similar-runs hint", exc_info=True)
        return
    for line in lines or ():
        print(line, file=sys.stderr)


def index_is_warm(storage, app_name):
    """Whether *app_name*'s experiment index is persisted on this host."""
    path_of = getattr(storage, "index_cache_path", None)
    path = path_of(app_name) if path_of else None
    return bool(path) and os.path.isfile(path)


def _wanted(args, exp_conf):
    if getattr(args, "similar_hint", None) is False or not hint_enabled(exp_conf):
        return False
    return not getattr(args, "parent", None) and not any(
        os.environ.get(name) for name in INNER_RUN_ENVS)


def _within_budget(work):
    """``work()``'s result when it is done within :data:`BUDGET_SEC`, else None."""
    started, done = _clock(), []

    def run():
        try:
            done.append(work())
        except Exception:
            VMN_LOGGER.debug("Similar-runs hint failed", exc_info=True)

    thread = threading.Thread(target=run, name="vmn-similar-hint", daemon=True)
    thread.start()
    thread.join(BUDGET_SEC)
    if thread.is_alive() or not done or _clock() - started > BUDGET_SEC:
        return None
    return done[0]


def _lines(storage, app_name, verstr, exp_conf):
    schema = conf_schema(exp_conf)
    snapshot = indexed_snapshot(storage, app_name, wait=True, fallback=None, schema=schema)
    if snapshot is None:
        return None
    target = run_target(snapshot, storage, app_name, verstr)
    if target["row"].get("parent"):
        return None
    items = search(storage, app_name, snapshot, target, schema=schema, top=HINT_TOP,
                   weights=conf_weights(exp_conf))
    return hint_lines(items)
