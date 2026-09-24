#!/usr/bin/env python3
"""Read-side access to experiments for the vmn ui API.

Pure, lock-free reads over the same storage layer the CLI uses. Rows are folded
by :mod:`version_stamp.core.experiment_log` — the module ``vmn exp`` folds its
own with — so the web leaderboard and the CLI always agree.
"""
import os

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core.experiment_log import filter_by_status, sort_by_metric
from version_stamp.core.experiment_log import load_log as _load_log
from version_stamp.core.experiment_query import filter_rows
from version_stamp.core.experiment_status import load_run_state
from version_stamp.core.experiment_tree import annotate_rows
from version_stamp.core.version_math import tag_name_to_app_name
from version_stamp.ui.readers.config import read_app_conf as _read_app_conf
from version_stamp.ui.readers.experiment_detail import experiment_detail
from version_stamp.ui.readers.versions import version_counts


def experiment_storage(root_path):
    return get_snapshot_storage("local", vmn_root_path=root_path, subdir="experiments")


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
            if rel == "." or rel.split(os.sep)[0].startswith("."):
                continue
            parts = rel.split(os.sep)
            if "branch_conf" in parts:
                continue
            if parts[-1] in ("snapshots", "experiments", "root_snapshots"):
                apps.add(os.sep.join(parts[:-1]).replace(os.sep, "/"))
                dirnames[:] = []
                continue
            if "conf.yml" in filenames:
                apps.add(rel.replace(os.sep, "/"))

    rows = []
    storage = experiment_storage(root_path)
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


def apply_filters(rows, status=None, query=None):
    """Both row filters, ANDed: the status whitelist then the query language.

    Runs after status derivation and before :func:`sort_rows`, which owns
    ordering and paging — so ``total`` counts the rows that matched. Raises
    :class:`~version_stamp.core.experiment_query.QueryError` on a bad *query*;
    the API turns that into a 400.
    """
    return filter_rows(filter_by_status(rows, status), query)


ORDERS = ("asc", "desc")
_DESCENDING = {"asc": False, "desc": True}


def sort_rows(rows, schema, sort=None, last=None, offset=0, limit=None, order=None):
    """Pure ordering over fetched rows — semantics identical to ``vmn exp list``.

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
    """List apps from a storage backend (S3). Limited: no version counts or conf.

    App keys are the tag form (``root/svc`` → ``root-svc``, bijective because
    ``-`` is illegal in app names), so ``my_app`` is never shown as ``my/app``.
    """
    apps = set()
    if hasattr(storage, "_s3") and hasattr(storage, "prefix"):
        try:
            for cp in storage._common_prefixes(storage.prefix + "/"):
                app_key = cp[len(storage.prefix) + 1 :].rstrip("/")
                apps.add(tag_name_to_app_name(app_key))
        except Exception:
            pass
    rows = []
    for name in sorted(apps):
        try:
            # Names only: counting must not fetch every run's metadata.
            exp_count = len(storage.list_verstrs(name))
        except Exception:
            exp_count = 0
        rows.append({"name": name, "experiments": exp_count, "versions": 0})
    return rows
