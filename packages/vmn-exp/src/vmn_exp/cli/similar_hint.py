"""The submission hint: once ``vmn-exp create``/``run`` claimed a run, the past
runs most like it, on stderr — before ``run`` starts the child::

    2 similar runs: best val_loss=0.31 — <verstr> by alice@x.io, 3w ago (<reasons>)
      <verstr> by bob@x.io, 2d ago (<reasons>)

Cheap or nothing. Its candidates are the app's index as this host last
persisted it, and there is no hint without one: it never refreshes the index
— a cold one means reading every record, and the process exit would wait for
a refresh's reads (a remote store's run on a thread pool), budget or not. Of
the store it reads only the new run's own record, which the cache predates.
The budget bounds the work, not just the wait: an index of more than
:data:`MAX_INDEXED_RUNS` runs (counted, not read) is never loaded, and a
search still loading at :data:`BUDGET_SEC` prints nothing and stops before
scoring (it runs on a daemon thread, so nothing waits for it). It is never
computed for inner runs (``--parent``, an enclosing run's
``VMN_EXPERIMENT_ID``, sweep trials), with ``--no-similar`` or with conf
``experiment.similar.hint: false``. Errors are logged at debug and never touch
the run. ``vmn-exp similar <app> -v <verstr>`` shows the rest — from a
refreshed index.
"""
import os
import sys
import threading
import time

from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.similar_output import hint_lines
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_snapshot import IndexSnapshot, new_side_tables, put_side_tables
from vmn_exp.core.index_store import IndexStore
from vmn_exp.core.index_views import lean_row
from vmn_exp.core.log import load_log
from vmn_exp.core.similar import target_from_snapshot
from vmn_exp.core.similar_search import conf_schema, conf_weights, hint_enabled, search

BUDGET_SEC = 0.3
# The most runs an index may hold for the hint to load and search it within
# the budget (about 0.05 ms a run on a laptop, with headroom); a bigger one
# would cost the command its time and memory, so it is never loaded.
MAX_INDEXED_RUNS = 4000
HINT_TOP = 3
# Set in an enclosing run's children (VMN_EXPERIMENT_ID) and in sweep trials.
INNER_RUN_ENVS = ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL")
_clock = time.monotonic


def print_hint(storage, app_name, verstr, args, exp_conf):
    """Print the hint for the new run *verstr*, when wanted and cheap."""
    try:
        if not _wanted(args, exp_conf):
            return
        path = _cache_path(storage, app_name)
        if not _searchable_in_budget(path, app_name):
            return
        lines = _within_budget(
            lambda expired: _lines(storage, app_name, verstr, exp_conf, path, expired))
    except Exception:
        VMN_LOGGER.debug("No similar-runs hint", exc_info=True)
        return
    for line in lines or ():
        print(line, file=sys.stderr)


def _searchable_in_budget(path, app_name):
    """Whether *app_name*'s index is persisted at *path* (warm) with at most
    :data:`MAX_INDEXED_RUNS` runs; counts them without loading any."""
    if not path or not os.path.isfile(path):
        return False
    store = IndexStore(path)
    try:
        return 0 < store.count(app_name) <= MAX_INDEXED_RUNS
    finally:
        store.close()


def _cache_path(storage, app_name):
    path_of = getattr(storage, "index_cache_path", None)
    return path_of(app_name) if path_of else None


def _wanted(args, exp_conf):
    if getattr(args, "similar_hint", None) is False or not hint_enabled(exp_conf):
        return False
    return not getattr(args, "parent", None) and not any(
        os.environ.get(name) for name in INNER_RUN_ENVS)


def _within_budget(work):
    """``work(expired)``'s result when it is done within :data:`BUDGET_SEC`,
    else None; the Event *expired* is set once nothing waits for it."""
    started, done, expired = _clock(), [], threading.Event()

    def run():
        try:
            done.append(work(expired))
        except Exception:
            VMN_LOGGER.debug("Similar-runs hint failed", exc_info=True)

    thread = threading.Thread(target=run, name="vmn-similar-hint", daemon=True)
    thread.start()
    thread.join(BUDGET_SEC)
    expired.set()
    if thread.is_alive() or not done or _clock() - started > BUDGET_SEC:
        return None
    return done[0]


def _lines(storage, app_name, verstr, exp_conf, path, expired):
    target = _new_run_target(storage, app_name, verstr)
    if target["row"].get("parent"):
        return None
    schema = conf_schema(exp_conf)
    snapshot = _cached_snapshot(path, app_name, schema)
    if expired.is_set():
        return None
    items = search(storage, app_name, snapshot, target, schema=schema, top=HINT_TOP,
                   weights=conf_weights(exp_conf))
    return hint_lines(items)


def _cached_snapshot(path, app_name, schema=None):
    """*app_name*'s index snapshot as persisted at *path*, under the metrics
    *schema*; reads nothing but that file."""
    store = IndexStore(path)
    try:
        return ExperimentIndex.follower(store, app_name).snapshot().summarized(schema)
    finally:
        store.close()


def _new_run_target(storage, app_name, verstr):
    """The similar-runs target of the run *verstr*, from its own record."""
    meta = storage.load_metadata(app_name, verstr)
    row, note, *values = lean_row(1, meta, fold_log(load_log(storage, app_name, verstr)))
    sides = new_side_tables()
    put_side_tables(sides, verstr, values)
    own = IndexSnapshot.build(app_name, 0, [row], {}, {verstr: note}, **sides)
    return target_from_snapshot(own, verstr, app=app_name)
