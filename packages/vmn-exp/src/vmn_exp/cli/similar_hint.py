"""The submission hint: once ``vmn-exp create``/``run`` claimed a run, the past
runs most like it, on stderr — before ``run`` starts the child::

    2 similar runs: best val_loss=0.31 — <verstr> by alice@x.io, 3w ago (<reasons>)
      <verstr> by bob@x.io, 2d ago (<reasons>)

Cheap or nothing. It searches the app's index file as this host last
persisted it, and there is no hint without one: it never refreshes the index
— a cold one means reading every record, and the process exit would wait for
a refresh's reads (a remote store's run on a thread pool), budget or not. Of
the store it reads only the new run's own record, which the file predates,
and only where the command just wrote it: the local side of a local-first
storage (its replica, or a direct-to-remote store's log buffer, which holds
every line of a run this process created) — never a remote, whose listings
no deadline can interrupt. ``vmn-exp run`` passes the command it runs (its
run state records it only once the child starts), so the hint ranks like
``vmn-exp similar -v`` on the run.
The budget (:data:`BUDGET_SEC`) bounds the work, not just the wait: the hint
runs on the calling thread, and the search takes it as a deadline that
interrupts its SQLite queries (a progress handler,
:class:`~vmn_exp.core.similar.SimilarDeadlineExceeded`); past it, nothing is
printed. Reading the new run is checked before the search. The search reads
the FTS table and the few runs it shows by verstr, so its cost does not grow
with the app. It is never computed for inner runs (``--parent``, an
enclosing run's ``VMN_EXPERIMENT_ID``, sweep trials), with ``--no-similar``
or with conf ``experiment.similar.hint: false``. Errors are logged at debug
and never touch the run. ``vmn-exp similar <app> -v <verstr>`` shows the
rest — from a refreshed index.
"""
import os
import sys
import time

from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.similar_output import hint_lines
from vmn_exp.core.similar import SimilarDeadlineExceeded
from vmn_exp.core.similar_corpus import file_scope
from vmn_exp.core.similar_search import (
    conf_schema,
    conf_weights,
    hint_enabled,
    index_path,
    record_target,
    search,
)
from vmn_exp.storage.cached import local_side

BUDGET_SEC = 0.3
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
        local = local_side(storage)
        path = index_path(storage, app_name)
        if local is None or not path or not os.path.isfile(path):
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
    target = record_target(local, app_name, verstr, command=command)
    if target["row"].get("parent"):
        return None
    _check(deadline)
    schema = conf_schema(exp_conf)
    scope = file_scope(app_name, path, schema, repair=False)
    if scope is None:
        return None
    items = search(local, app_name, scope, target, schema=schema, top=HINT_TOP,
                   weights=conf_weights(exp_conf), deadline=deadline)
    _check(deadline)
    return hint_lines(items)
