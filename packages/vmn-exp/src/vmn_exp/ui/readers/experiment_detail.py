#!/usr/bin/env python3
"""One experiment's detail for the vmn-exp ui API, bounded however long it ran.

A run page polls this while the run is live, so its cost must not grow with the
log or with the workspace: the log is returned as a tail (the rest is paged via
:func:`log_page`), every metric series is thinned to a chart's worth of points,
patch presence comes from the metadata flags instead of the tarball, and the
run tree is answered from an index snapshot's parent edges. The parsed
log is reused across polls and log pages, and a grown local log costs only its
new bytes (:mod:`~vmn_exp.ui.readers.parsed_logs`).
"""
from collections import ChainMap

import yaml

from vmn_exp.snapshot import _resolve_verstr
from vmn_exp.core.fold import fold_inputs_dict
from vmn_exp.core.log import last_metric_at, list_artifacts
from vmn_exp.core.log import load_log as _load_log
from vmn_exp.core.refs import placement_snapshot
from vmn_exp.core.step_metric import step_metrics
from vmn_exp.core.status import (
    load_run_state,
    run_state_observed_at,
    status_fields,
)
from vmn_exp.core.tree import children_by_parent, fleet_summary, run_status
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.parsed_logs import LogSnapshot, ParsedLogs
from vmn_exp.ui.readers.patches import patch_presence
from vmn_exp.ui.readers.series import DEFAULT_MAX_POINTS, points_per_metric

_ENV_SIZE_CAP = 256 * 1024  # 256 KB

LOG_TAIL = 200


def _load_env(storage, app_name, verstr, metadata):
    """``env`` payload for the detail: full dict when env.yml fits, else summary.

    Returns the full env dict when env.yml is present and at most
    ``_ENV_SIZE_CAP`` bytes.  When the file is larger, returns the compact
    summary from *metadata* with ``truncated: True`` added.  Returns ``None``
    when neither env.yml nor a summary is available.
    """
    raw = storage.load_file(app_name, verstr, "env.yml")  # bytes or None
    if raw is not None:
        if len(raw) <= _ENV_SIZE_CAP:
            try:
                return yaml.safe_load(raw)
            except Exception:
                pass
        summary = metadata.get("env")
        return dict(summary, truncated=True) if summary else None
    return metadata.get("env") or None


_DETAIL_STATUS_KEYS = tuple(status_fields(None)) + (
    "parent",
    "children",
    "kind",
    "depth",
    "tree_status",
    "last_metric_at",
    "fleet",
)


def _placement_edges(storage, app_name):
    """The default edges provider: the app's index snapshot's."""
    return placement_snapshot(storage, app_name).edges


# ``{parent: [child]}`` per edges mapping: a provider hands back the same
# mapping while the edges are unchanged, so a poll costs a lookup.
_CHILDREN = LRU(8)
_PARSED = ParsedLogs()


def _children_of(parent_of):
    return _CHILDREN.per_snapshot(
        parent_of,
        lambda: children_by_parent({"verstr": v, "parent": p} for v, p in parent_of.items()),
        key=(len(parent_of),),
    )


def status_detail(
    storage,
    app_name,
    verstr,
    metadata,
    log,
    edges,
    read_run_state=load_run_state,
    read_observed_at=run_state_observed_at,
    read_child_row=None,
):
    """Status payload with the run's place in the tree.

    Reads the run state of the subtree only; *metadata* and *log* (a list or
    a :class:`LogSnapshot`) come from the caller, which already loaded both.
    *edges* is a ``(storage, app_name) -> {verstr: parent}`` provider; it
    should hand back the same mapping while nothing changed, which makes the
    tree lookup a dict lookup. *read_observed_at* gives each member's
    run_state.yml store write time, which stuck detection weighs too.
    """
    edges_of = edges(storage, app_name)
    parent_of = edges_of
    if verstr not in edges_of:  # not indexed yet: overlay, never copy the rest
        parent_of = ChainMap({verstr: metadata.get("parent")}, edges_of)
    children_of = _children_of(edges_of)
    read_state_fn = lambda v: read_run_state(storage, app_name, v)
    observed_at_fn = lambda v: read_observed_at(storage, app_name, v)
    detail = run_status(
        verstr,
        parent_of,
        read_state_fn,
        observed_at=observed_at_fn,
        children_of=children_of,
    )
    detail["parent"] = metadata.get("parent")
    detail["last_metric_at"] = (
        log.last_metric_at if isinstance(log, LogSnapshot) else last_metric_at(log)
    )

    fleet = None
    if detail.get("kind") == "outer":
        expected = None
        if isinstance(log, LogSnapshot):
            ep = log.params.get("expected_pods")
            if isinstance(ep, (int, float)):
                expected = int(ep)
        detail["fleet"] = fleet_summary(
            verstr, children_of, read_state_fn,
            observed_at=observed_at_fn, expected=expected,
            read_child_row=read_child_row,
        )
    else:
        detail["fleet"] = None

    return {k: detail.get(k) for k in _DETAIL_STATUS_KEYS}


def _resolve(storage, app_name, verstr_ref, resolve=None):
    """``(verstr, metadata, error)`` for a ref, loading metadata only.

    *resolve* (``ref -> (verstr, error)``, e.g. an index snapshot's) is tried
    first; storage answers what it cannot, such as a run it has not seen yet.
    """
    if resolve:
        verstr, err = resolve(verstr_ref)
    if not resolve or err:
        verstr, err = _resolve_verstr(storage, app_name, verstr_ref, kind="experiment")
    if err:
        return None, None, err
    metadata = storage.load_metadata(app_name, verstr)
    if metadata is None:
        return None, None, f"Experiment {verstr} not found"
    return verstr, metadata, None


def experiment_detail(
    storage,
    app_name,
    verstr_ref,
    edges=None,
    max_points=DEFAULT_MAX_POINTS,
    include_log=False,
    read_log=_load_log,
    read_run_state=load_run_state,
    keys=None,
    include_series=True,
    resolve=None,
    read_observed_at=run_state_observed_at,
    read_child_row=None,
    x=None,
    schema=None,
):
    """``(detail, error)``; the ref supports @N / prefix / 'latest'.

    ``log`` is the tail unless *include_log*; ``log_tail`` / ``log_total`` and
    ``series_total`` let a client page the log and label thinned charts.
    *keys* restricts ``series`` to those metrics; ``include_series=False``
    omits them. *read_log* / *read_run_state* are the reader's own loaders;
    *resolve* resolves the ref before storage is asked (see :func:`_resolve`);
    *read_observed_at* is the run-state store write time loader. *x* joins
    the series on another metric (see :func:`thinned_series`);
    ``step_metrics`` lists what the run and the metrics *schema* declare;
    ``metrics`` (each metric's summary value) and ``metric_summary`` follow
    the run's and the *schema*'s summary policies.
    """
    verstr, metadata, err = _resolve(storage, app_name, verstr_ref, resolve)
    if err:
        return None, err

    snapshot = _PARSED.get(storage, app_name, verstr, read_log)
    tail = snapshot.tail(LOG_TAIL)
    series, series_total = (
        thinned_series(snapshot, keys, max_points, x=x) if include_series else ({}, {})
    )
    metrics, metric_summary = snapshot.summarized_metrics(schema)
    return {
        "metadata": metadata,
        "log": snapshot.log() if include_log else tail,
        "log_tail": tail,
        "log_total": snapshot.total,
        "params": snapshot.params,
        "metrics": metrics,
        "metric_summary": metric_summary,
        "series": series,
        "series_total": series_total,
        "step_metrics": declared_step_metrics(snapshot, schema),
        "artifacts": list_artifacts(storage, app_name, verstr),
        **snapshot.media,
        "status": status_detail(
            storage,
            app_name,
            verstr,
            metadata,
            snapshot,
            edges or _placement_edges,
            read_run_state=read_run_state,
            read_observed_at=read_observed_at,
            read_child_row=read_child_row,
        ),
        "patches": patch_presence(storage, app_name, verstr, metadata),
        "env": _load_env(storage, app_name, verstr, metadata),
        "inputs": fold_inputs_dict(snapshot._parsed.fold) or None,
        "imported_from": metadata.get("imported_from"),
        "forked_from": metadata.get("forked_from"),
        "rewinds": snapshot.rewinds(),
    }, None


_THINNED_PER_SNAPSHOT = 4


def _x_of(names, x):
    """``{metric: x metric}`` for the *names* to join: *x* is a metric name
    (every other metric) or such a map; None joins nothing."""
    if x is None:
        return {}
    if isinstance(x, str):
        return {k: x for k in names if k != x}
    return {k: x[k] for k in names if k in x and x[k] != k}


def thinned_series(snapshot, keys, max_points, budget=None, x=None):
    """``(series, series_total)`` of *keys* (None: all), thinned so they stay
    within *budget* points in all (default: the per-response cap). With *x*
    (see :func:`_x_of`) those metrics are joined on their x metric first.
    Memoized on the snapshot, so an unchanged run's poll does not thin again."""
    known = snapshot.series_keys()
    names = list(known) if keys is None else [k for k in keys if k in known]
    if isinstance(x, str):
        names = [k for k in names if k != x]
    x_of = _x_of(names, x)
    per_metric = points_per_metric(max_points, len(names), budget)
    memo_key = (tuple(names), per_metric, tuple(sorted(x_of.items())))
    hit = snapshot.memo.get(memo_key)
    if hit is None:
        hit = _thin(snapshot, names, x_of, per_metric)
        if len(snapshot.memo) >= _THINNED_PER_SNAPSHOT:
            snapshot.memo.clear()
        snapshot.memo[memo_key] = hit
    return hit


def _thin(snapshot, names, x_of, per_metric):
    series, totals = snapshot.thinned([k for k in names if k not in x_of], per_metric)
    joined, joined_totals = snapshot.joined(x_of, per_metric)
    series.update(joined)
    totals.update(joined_totals)
    return {k: series[k] for k in names}, {k: totals[k] for k in names}


def declared_step_metrics(snapshot, schema=None):
    """``{metric: x metric}`` the run's definitions and *schema* declare."""
    return step_metrics(snapshot.series_keys(), snapshot.definitions, schema)


def run_series(
    storage, app_name, verstr, keys=None, max_points=DEFAULT_MAX_POINTS, budget=None,
    x=None, schema=None,
):
    """``(series, series_total, step_metrics)`` of an existing run, or None
    when it is gone."""
    if storage.load_metadata(app_name, verstr) is None:
        return None
    snapshot = _PARSED.get(storage, app_name, verstr, _load_log)
    series, totals = thinned_series(snapshot, keys, max_points, budget, x)
    return series, totals, declared_step_metrics(snapshot, schema)


def log_page(
    storage, app_name, verstr_ref, offset=0, limit=LOG_TAIL, read_log=_load_log,
    resolve=None,
):
    """``({"entries", "total"}, error)`` — a slice of the log, oldest first."""
    verstr, _, err = _resolve(storage, app_name, verstr_ref, resolve)
    if err:
        return None, err
    snapshot = _PARSED.get(storage, app_name, verstr, read_log)
    entries = snapshot.page(int(offset), int(limit))
    return {"entries": entries, "total": snapshot.total}, None
