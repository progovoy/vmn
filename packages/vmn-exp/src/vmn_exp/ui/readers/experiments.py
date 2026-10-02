#!/usr/bin/env python3
"""Read-side access to experiments for the vmn-exp ui API.

Pure, lock-free reads over the same storage layer the CLI uses. Rows are folded
by :mod:`vmn_exp.core.log` — the module ``vmn-exp`` folds its
own with — so the web leaderboard and the CLI always agree.
"""
import os

from vmn_exp.storage.areas import RUNS, SNAPSHOTS, local_store_root
from vmn_exp.storage.open import open_storage
from vmn_exp.core.log import filter_by_status, sort_by_metric
from vmn_exp.core.log import load_log as _load_log
from vmn_exp.core.query import filter_rows
from vmn_exp.core.status import load_run_state
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui.readers.config import read_app_conf as _read_app_conf
from vmn_exp.ui.readers.experiment_detail import experiment_detail
from vmn_exp.ui.readers.versions import version_counts


def experiment_storage(root_path):
    return open_storage(None, local_store_root(root_path), area=RUNS, writer=False)


def metrics_schema(root_path, app_name):
    exp_conf = _read_app_conf(root_path, app_name).get("experiment") or {}
    return exp_conf.get("metrics", {}) or {}


def list_apps(root_path):
    """All vmn apps in a checkout: configured (.vmn/<app>/conf.yml) plus any
    with experiment/snapshot data. Returns rows with experiment counts."""
    vmn_dir = os.path.join(root_path, ".vmn")
    apps = set()
    if os.path.isdir(vmn_dir):
        for dirpath, dirnames, filenames in os.walk(vmn_dir):
            rel = os.path.relpath(dirpath, vmn_dir)
            if rel == "store":  # the repo-local store: listed below
                dirnames[:] = []
                continue
            if rel == "." or rel.split(os.sep)[0].startswith("."):
                continue
            parts = rel.split(os.sep)
            if "branch_conf" in parts:
                continue
            if parts[-1] in ("snapshots", "experiments", "root_snapshots"):
                name = os.sep.join(parts[:-1]).replace(os.sep, "/")
                apps.add(name)
                dirnames[:] = []
                continue
            if "conf.yml" in filenames:
                name = rel.replace(os.sep, "/")
                apps.add(name)

    rows = []
    storage = experiment_storage(root_path)
    apps.update(storage.list_apps())
    apps.update(storage.in_area(SNAPSHOTS).list_apps())
    ver_counts = version_counts(root_path)
    for name in sorted(apps):
        try:
            # Names only: counting must not parse every run's metadata.
            exp_count = len(storage.list_verstrs(name))
        except Exception:
            exp_count = 0
        rows.append(
            {
                "name": name,
                "experiments": exp_count,
                "versions": ver_counts.get(name, 0),
            }
        )
    return rows


def apply_filters(rows, status=None, query=None, snapshot=None):
    """Both row filters, ANDed: the status whitelist then the query language.

    Runs after status derivation and before :func:`sort_rows`, which owns
    ordering and paging — so ``total`` counts the rows that matched. Raises
    :class:`~version_stamp.core.experiment_query.QueryError` on a bad *query*;
    the API turns that into a 400. *snapshot*: the index snapshot the lean
    *rows* came from, whose ``outputs`` a query may read.
    """
    extra = {"outputs": snapshot.outputs_of} if snapshot is not None else None
    return filter_rows(filter_by_status(rows, status), query, extra=extra)


ORDERS = ("asc", "desc")
_DESCENDING = {"asc": False, "desc": True}


def sort_rows(rows, schema, sort=None, last=None, offset=0, limit=None, order=None):
    """Pure ordering over fetched rows — semantics identical to ``vmn-exp list``.

    *sort* is a metric name or ``"timestamp"`` (newest first by default);
    *order* (``asc``/``desc``) overrides the direction — rows missing the metric
    stay last either way. When *limit* is given, returns
    ``{"rows": [...], "total": N}`` for paginated responses. Without *limit*,
    returns a plain list (backward compatible).
    """
    if last:
        rows = rows[-int(last) :]
    rows = sort_by_metric(
        list(rows), schema, sort=sort, descending=_DESCENDING.get(order)
    )

    if limit is not None:
        total = len(rows)
        rows = rows[offset : offset + limit]
        return {"rows": rows, "total": total}
    return rows


def leaderboard(
    rows,
    run_states,
    schema,
    sort=None,
    last=None,
    offset=0,
    limit=None,
    status=None,
    query=None,
    order=None,
    observed_at=None,
):
    """The one list pipeline: derive status, filter, then order and page.

    Status is derived from the current time and ``query`` is per request, so
    neither is ever cached — callers pass freshly fetched rows. *observed_at*
    is ``{verstr: run_state.yml store write time}``.
    """
    annotated = annotate_rows(rows, run_states, observed_at=observed_at)
    return sort_rows(
        apply_filters(annotated, status, query),
        schema,
        sort=sort,
        last=last,
        offset=offset,
        limit=limit,
        order=order,
    )


def facets(rows):
    """The filter vocabulary of *rows*: distinct branches, metric and param keys."""
    branches, metric_keys, param_keys = set(), set(), set()
    for row in rows:
        if row.get("branch"):
            branches.add(str(row["branch"]))
        metric_keys.update(row.get("metrics") or {})
        param_keys.update(row.get("params") or {})
    return {
        "branches": sorted(branches),
        "metric_keys": sorted(metric_keys),
        "param_keys": sorted(param_keys),
        "total": len(rows),
    }


def get_experiment_from_storage(
    storage, app_name, verstr_ref, read_run_state=None, **detail_opts
):
    """Get experiment detail from storage backend directly.

    *read_run_state* defaults to reading each subtree run state from storage.
    """
    return experiment_detail(
        storage,
        app_name,
        verstr_ref,
        read_log=_load_log,
        read_run_state=read_run_state or load_run_state,
        **detail_opts,
    )


def list_apps_from_storage(storage):
    """The apps of a store workspace. Limited: no version counts or conf."""
    rows = []
    for name in storage.list_apps():
        try:
            # Names only: counting must not fetch every run's metadata.
            exp_count = len(storage.list_verstrs(name))
        except Exception:
            exp_count = 0
        rows.append({"name": name, "experiments": exp_count, "versions": 0})
    return rows
