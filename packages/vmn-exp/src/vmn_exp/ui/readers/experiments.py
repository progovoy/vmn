#!/usr/bin/env python3
"""Read-side access to experiments for the vmn-exp ui API.

Pure, lock-free reads over the same storage layer the CLI uses. Rows are folded
by :mod:`vmn_exp.core.log` — the module ``vmn-exp`` folds its
own with — so the web leaderboard and the CLI always agree.
"""
import os

from vmn_exp.core.log import filter_by_status, sort_by_metric
from vmn_exp.core.log import load_log as _load_log
from vmn_exp.core.query import filter_rows
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.core.status import load_run_state
from vmn_exp.core.values import is_finite_number
from vmn_exp.core.tree import annotate_rows
from vmn_exp.storage.areas import RUNS, SNAPSHOTS, local_store_root
from vmn_exp.storage.open import open_storage
from vmn_exp.ui.facet_values import distinct_count, value_key
from vmn_exp.ui.failure_signature import signed
from vmn_exp.ui.freshness import DEFAULT_STALE_AFTER_MIN
from vmn_exp.ui.readers.branch_conf import app_conf_path
from vmn_exp.ui.readers.config import read_app_conf as _read_app_conf
from vmn_exp.ui.readers.config import read_conf_file
from vmn_exp.ui.readers.experiment_detail import experiment_detail
from vmn_exp.ui.readers.versions import version_counts


def experiment_storage(root_path):
    return open_storage(None, local_store_root(root_path), area=RUNS, writer=False)


def experiment_conf(root_path, app_name):
    """The app conf.yml's ``experiment`` section, or ``{}``."""
    return _read_app_conf(root_path, app_name).get("experiment") or {}


def metrics_schema(root_path, app_name):
    return experiment_conf(root_path, app_name).get("metrics", {}) or {}


def conf_ui(root_path, app_name):
    """``experiment.ui`` of the conf the app reads on the checkout's branch
    (its branch conf, if any), or ``{}``."""
    conf = read_conf_file(app_conf_path(root_path, app_name))
    ui = (conf.get("experiment") or {}).get("ui")
    return ui if isinstance(ui, dict) else {}


def stale_after_min(root_path, app_name):
    """Minutes past which the dashboard says the app's data is stale (see
    :func:`stale_after_of`)."""
    return stale_after_of(conf_ui(root_path, app_name))


def stale_after_of(ui):
    """*ui*'s ``stale_after_min`` when a positive number, else
    :data:`~vmn_exp.ui.freshness.DEFAULT_STALE_AFTER_MIN`."""
    value = ui.get("stale_after_min")
    return value if is_finite_number(value) and value > 0 else DEFAULT_STALE_AFTER_MIN


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
    *rows* came from, whose ``outputs``, run tree, intents and similar-runs
    documents a query may read (:func:`~vmn_exp.core.query_extra.lean_extra`).
    """
    return filter_rows(filter_by_status(rows, status), query, extra=lean_extra(snapshot))


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
    annotated = [signed(row) for row in annotate_rows(rows, run_states, observed_at=observed_at)]
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
    """The filter and Group by vocabulary of *rows*: distinct branches,
    metric, param and tag keys, distinct values per param (capped), and how
    many rows have a parent."""
    branches, metric_keys, tag_keys = set(), set(), set()
    param_values = {}
    parented = 0
    for row in rows:
        if row.get("branch"):
            branches.add(str(row["branch"]))
        metric_keys.update(row.get("metrics") or {})
        for key, value in (row.get("params") or {}).items():
            param_values.setdefault(key, set()).add(value_key(value))
        tag_keys.update(row.get("tags") or {})
        parented += bool(row.get("parent"))
    return {
        "branches": sorted(branches),
        "metric_keys": sorted(metric_keys),
        "param_keys": sorted(param_values),
        "tag_keys": sorted(tag_keys),
        "param_values": {k: distinct_count(v) for k, v in sorted(param_values.items())},
        "parented": parented,
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


def list_apps_from_storage(storage, persisted_count=None):
    """The apps of a store workspace. Limited: no version counts or conf.
    With *persisted_count(name)* (the server's), an app's run count is what
    its index holds, None before it holds any (its experiments-status fills
    it in): listing 45k runs by name takes S3 tens of seconds."""
    rows = []
    for name in storage.list_apps():
        if persisted_count is not None:
            exp_count = persisted_count(name) or None
        else:
            exp_count = _listed_count(storage, name)
        rows.append({"name": name, "experiments": exp_count, "versions": 0})
    return rows


def _listed_count(storage, name):
    try:
        # Names only: counting must not fetch every run's metadata.
        return len(storage.list_verstrs(name))
    except Exception:
        return 0
