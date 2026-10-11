"""The submission hint: once ``vmn-exp create``/``run`` claimed a run, the past
runs most like it, on stderr — before ``run`` starts the child::

    2 similar runs: best val_loss=0.31 — <verstr> by alice@x.io, 3w ago (<reasons>)
      <verstr> by bob@x.io, 2d ago (<reasons>)

Cheap or nothing. Its candidates are the app's index as this host last
persisted it, and there is no hint without one: it never refreshes the index
— a cold one means reading every record, and the process exit would wait for
a refresh's reads (a remote store's run on a thread pool), budget or not. Of
the store it reads only the new run's own record, which the cache predates,
and only where the command just wrote it: the local side of a local-first
storage (its replica, or a direct-to-remote store's log buffer, which holds
every line of a run this process created) — never a remote, whose listings
no deadline can interrupt. ``vmn-exp run`` passes the command it runs (its
run state records it only once the child starts), so the hint ranks like
``vmn-exp similar -v`` on the run.
The budget (:data:`BUDGET_SEC`) bounds the work, not just the wait: the hint
runs on the calling thread, so nothing is left running past it, and the
search takes it as a deadline it checks while it builds its index and scores
(:class:`~vmn_exp.core.similar.SimilarDeadlineExceeded`); past it, nothing is
printed. The steps it cannot interrupt — reading the new run, loading the
persisted index — are checked between, and an index too big to load within
the budget is never loaded (:func:`_searchable_in_budget`). It is never
computed for inner runs (``--parent``, an enclosing run's
``VMN_EXPERIMENT_ID``, sweep trials), with ``--no-similar`` or with conf
``experiment.similar.hint: false``. Errors are logged at debug and never touch
the run. ``vmn-exp similar <app> -v <verstr>`` shows the rest — from a
refreshed index.
"""
import os
import sys
import time

from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.similar_output import hint_lines
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_snapshot import IndexSnapshot, new_side_tables, put_side_tables
from vmn_exp.core.index_store import IndexStore
from vmn_exp.core.index_views import lean_row
from vmn_exp.core.log import load_log
from vmn_exp.core.similar import SimilarDeadlineExceeded, target_from_snapshot
from vmn_exp.core.similar_search import conf_schema, conf_weights, hint_enabled, search
from vmn_exp.storage.cached import CachedSnapshotStorage

BUDGET_SEC = 0.3
# The most runs an index may hold for the hint to load it within the budget
# (about 0.05 ms a run on a laptop, with headroom): see _searchable_in_budget.
MAX_INDEXED_RUNS = 4000
HINT_TOP = 3
# Set in an enclosing run's children (VMN_EXPERIMENT_ID) and in sweep trials.
INNER_RUN_ENVS = ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL")
# The search's clock (time.monotonic): the deadline handed to it is read off this.
_clock = time.monotonic


def print_hint(storage, app_name, verstr, args, exp_conf, command=None):
    """Print the hint for the new run *verstr* (running *command*, an argv),
    when wanted and found within :data:`BUDGET_SEC`."""
    deadline = _clock() + BUDGET_SEC
    try:
        if not _wanted(args, exp_conf):
            return
        local = _local_side(storage)
        path = _cache_path(storage, app_name)
        if local is None or not _searchable_in_budget(path, app_name):
            return
        lines = _lines(local, app_name, verstr, exp_conf, path, deadline, command)
    except SimilarDeadlineExceeded:
        VMN_LOGGER.debug("No similar-runs hint: past its time budget")
        return
    except Exception:
        VMN_LOGGER.debug("No similar-runs hint", exc_info=True)
        return
    for line in lines or ():
        print(line, file=sys.stderr)


def _searchable_in_budget(path, app_name):
    """Whether *app_name*'s index is persisted at *path* (warm) with at most
    :data:`MAX_INDEXED_RUNS` runs; counts them without loading any.

    The cap exists because loading the persisted index is one read the
    deadline cannot interrupt, unlike the search after it: an index too big
    to load within the budget would cost the command its time and memory
    only to be dropped, so it is never loaded."""
    if not path or not os.path.isfile(path):
        return False
    store = IndexStore(path)
    try:
        return 0 < store.count(app_name) <= MAX_INDEXED_RUNS
    finally:
        store.close()


def _local_side(storage):
    """The storage the command wrote the new run to locally: a local-first
    storage's local side, else *storage* unless it is remote (None)."""
    if isinstance(storage, CachedSnapshotStorage):
        # Private, but the cache's documented shape; it has no public accessor.
        return storage._local
    return None if getattr(storage, "is_remote", lambda: False)() else storage


def _cache_path(storage, app_name):
    path_of = getattr(storage, "index_cache_path", None)
    return path_of(app_name) if path_of else None


def _wanted(args, exp_conf):
    if getattr(args, "similar_hint", None) is False or not hint_enabled(exp_conf):
        return False
    return not getattr(args, "parent", None) and not any(
        os.environ.get(name) for name in INNER_RUN_ENVS)


def _check(deadline):
    """Raise :class:`SimilarDeadlineExceeded` once *deadline* has passed."""
    if _clock() >= deadline:
        raise SimilarDeadlineExceeded


def _lines(local, app_name, verstr, exp_conf, path, deadline, command):
    target = _new_run_target(local, app_name, verstr, command)
    if target["row"].get("parent"):
        return None
    _check(deadline)
    schema = conf_schema(exp_conf)
    snapshot = _cached_snapshot(path, app_name, schema)
    _check(deadline)
    items = search(local, app_name, snapshot, target, schema=schema, top=HINT_TOP,
                   weights=conf_weights(exp_conf), deadline=deadline)
    _check(deadline)
    return hint_lines(items)


def _cached_snapshot(path, app_name, schema=None):
    """*app_name*'s index snapshot as persisted at *path*, under the metrics
    *schema*; reads nothing but that file."""
    store = IndexStore(path)
    try:
        return ExperimentIndex.follower(store, app_name).snapshot().summarized(schema)
    finally:
        store.close()


def _new_run_target(local, app_name, verstr, command=None):
    """The similar-runs target of the run *verstr*, running *command*, from
    its own record in the *local* storage."""
    meta = local.load_metadata(app_name, verstr)
    row, note, *values = lean_row(1, meta, fold_log(load_log(local, app_name, verstr)))
    sides = new_side_tables()
    put_side_tables(sides, verstr, values)
    own = IndexSnapshot.build(app_name, 0, [row], {}, {verstr: note}, **sides)
    target = target_from_snapshot(own, verstr, app=app_name)
    if command:
        target["command"] = list(command)
    return target
