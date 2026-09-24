#!/usr/bin/env python3
"""The programmatic read side of ``vmn exp``: query runs from Python.

::

    from version_stamp.exp.reader import get_run, list_runs

    for run in list_runs(status="failed"):
        print(run["verstr"], run["metrics"])

Rows carry exactly what the dashboard shows for a run: its metadata, the latest
value of every metric, the derived status fields and its place in the run tree.

Status is *derived* on every call — a run whose heartbeat went stale reports
``stuck`` the next time it is read, never the ``running`` it last claimed. What
is cached is the folded files: :func:`list_runs` reads through the experiment
index (:mod:`version_stamp.core.experiment_index`, persisted as
``.index.sqlite`` beside the records), which re-reads only what changed.

Depends on ``version_stamp.core`` and the snapshot storage helpers only, never
on ``version_stamp.ui``, so the experiment feature can be lifted out later. The
log folding it shares with the CLI and the ui lives in
:mod:`version_stamp.core.experiment_log`.
"""
import os

import yaml

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core import experiment_index
from version_stamp.core.experiment_log import (
    experiment_row,
    filter_archived,
    filter_by_status,
    list_artifacts,
    metric_series,
    sort_by_metric,
)
from version_stamp.core.experiment_log import load_log as _load_log
from version_stamp.core.experiment_query import filter_rows
from version_stamp.core.experiment_refs import placement_snapshot, resolve_experiment
from version_stamp.core.experiment_status import (
    load_run_state,
    observed_at_by_verstr,
    run_state_observed_at,
    status_fields,
)
from version_stamp.core.experiment_tree import annotate_tree, subtree_status
from version_stamp.core.utils import resolve_root_path
from version_stamp.exp import _resolve_app_name

EXPERIMENTS_DIR = "experiments"


# ---------------------------------------------------------------------------
# Resolving what the caller left out
# ---------------------------------------------------------------------------


def _experiment_storage(root_path):
    """The checkout's local experiments. An S3 workspace passes its own storage."""
    return get_snapshot_storage(
        "local", vmn_root_path=root_path, subdir=EXPERIMENTS_DIR
    )


def _apps_with_experiments(root_path):
    """Every app under ``.vmn`` that has an experiments directory."""
    vmn_dir = os.path.join(root_path, ".vmn")
    apps = []
    for dirpath, dirnames, _ in os.walk(vmn_dir):
        if os.path.basename(dirpath) != EXPERIMENTS_DIR:
            continue
        dirnames[:] = []  # experiment dirs, nothing to look for inside
        rel = os.path.relpath(os.path.dirname(dirpath), vmn_dir)
        apps.append(rel.replace(os.sep, "/"))
    return sorted(apps)


def _resolve(app_name, storage):
    """Fill in the app name and storage from the current repo.

    Returns ``(app_name, storage, root_path)``; *root_path* is None when the
    caller supplied both, since then no checkout is involved (an S3 workspace,
    say) and there is no conf.yml to read.
    """
    root_path = None if (app_name and storage) else resolve_root_path()
    app_name = _resolve_app_name(app_name, lambda: _apps_with_experiments(root_path))
    return app_name, storage or _experiment_storage(root_path), root_path


def _metrics_schema(root_path, app_name):
    """``experiment.metrics`` from the app's conf.yml — drives sort direction.

    The app conf only, like the ui reads it; branch confs are not consulted.
    """
    if root_path is None:
        return {}
    path = os.path.join(root_path, ".vmn", app_name.replace("/", os.sep), "conf.yml")
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    conf = data.get("conf") or {}
    return (conf.get("experiment") or {}).get("metrics") or {}


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _all_rows(app_name, storage, use_index=True):
    """Every run of an app, status-annotated, in storage order (oldest first).

    With *use_index* the rows come from the experiment index, which re-reads
    only what changed since the last call; without, every run's log and run
    state is read. Asking about a single run goes through
    :func:`_subtree_row` instead.
    """
    if use_index:
        rows, run_states, observed = experiment_index.indexed_status_rows(
            storage, app_name
        )
    else:
        rows, run_states = experiment_index.direct_rows(
            storage, app_name, read_log=_load_log, read_run_state=load_run_state
        )
        observed = observed_at_by_verstr(storage, app_name, run_states)
    for row in rows:
        verstr = row["verstr"]
        row.update(status_fields(run_states.get(verstr), observed_at=observed.get(verstr)))
    return annotate_tree(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_runs(
    app_name=None,
    *,
    storage=None,
    sort=None,
    last=None,
    status=None,
    query=None,
    use_index=True,
    include_archived=False,
):
    """Runs of an app, oldest first unless *sort* or a primary metric reorders.

    Args:
        app_name: the vmn app; inferred from the current repo when omitted.
        storage: a snapshot storage backend; the local checkout's when omitted.
            Passing one together with *app_name* skips the checkout entirely, so
            there is no conf.yml to take sort direction from.
        sort: a metric name to order by.
        last: keep only the *last* runs (applied before sorting).
        status: keep only these statuses — a list or a comma-separated string.
        query: an experiment query (``metrics.loss < 0.5 and params.model = "xgb"``),
            ANDed with *status* and applied before *last* and *sort*. Raises
            :class:`~version_stamp.core.experiment_query.QueryError` when it will
            not compile — a caller wants the error, not a silent empty list.
        use_index: read through the incremental experiment index cached at
            ``<experiments dir>/.index.sqlite`` — what ``vmn exp list`` and the
            ui use — so repeated calls re-read only what changed. Status is
            still derived per call. On by default; ``use_index=False`` reads
            every run straight from storage (and writes no index file).
        include_archived: also return archived runs (hidden by default; see
            :mod:`version_stamp.exp.manage`).
    """
    app_name, storage, root_path = _resolve(app_name, storage)
    rows = _all_rows(app_name, storage, use_index=use_index)
    rows = filter_archived(rows, include_archived)
    rows = filter_rows(filter_by_status(rows, status), query)
    if last:
        rows = rows[-int(last) :]
    return sort_by_metric(rows, _metrics_schema(root_path, app_name), sort=sort)


def _subtree_row(app_name, storage, verstr, snapshot):
    """The row for one run, costing the run's subtree rather than the workspace.

    The placement *snapshot* gives the parent/child edges and the row's index;
    the run's own metadata is the only record read, and run states are read for
    the subtree alone, which is all ``tree_status`` can depend on. No log is
    read here — the caller loads the one it needs.
    """
    row = snapshot.row(verstr)
    meta = storage.load_metadata(app_name, verstr) if row else None
    if meta is None:
        return None, None

    observed_at = lambda v: run_state_observed_at(storage, app_name, v)  # noqa: E731
    run_state, tree = subtree_status(
        verstr,
        dict(snapshot.edges),
        lambda v: load_run_state(storage, app_name, v),
        observed_at=observed_at,
    )
    status = status_fields(run_state, observed_at=observed_at(verstr))
    status.update(tree)
    return {"idx": row["idx"], "meta": meta}, status


def get_run(app_name=None, ref="latest", *, storage=None):
    """One run: a :func:`list_runs` row plus its ``log``, ``series`` and ``artifacts``.

    *ref* takes whatever the CLI takes — a full verstr, a unique prefix, ``@N``
    or ``latest``. Raises ValueError when it resolves to nothing.
    """
    app_name, storage, _ = _resolve(app_name, storage)
    snapshot = placement_snapshot(storage, app_name)
    verstr, err = resolve_experiment(
        storage, app_name, ref or "latest", snapshot=snapshot
    )
    if err:
        raise ValueError(err)

    target, status = _subtree_row(app_name, storage, verstr, snapshot)
    if target is None:
        raise ValueError(f"Experiment '{verstr}' not found for {app_name}")

    log = _load_log(storage, app_name, verstr)
    row = experiment_row(target["idx"], target["meta"], log)
    row.update(status)
    row["log"] = log
    row["series"] = metric_series(log)
    row["artifacts"] = list_artifacts(storage, app_name, verstr)
    return row
