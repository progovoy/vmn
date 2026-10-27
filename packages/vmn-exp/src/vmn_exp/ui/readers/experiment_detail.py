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

from vmn_exp.core.fold import fold_inputs_dict, fold_outputs_dict
from vmn_exp.core.log import last_metric_at, list_artifacts
from vmn_exp.core.log import load_log as _load_log
from vmn_exp.core.metric_compact import record_compacted
from vmn_exp.core.refs import placement_snapshot
from vmn_exp.core.resolve_ref import RefError
from vmn_exp.core.run_error import ERROR_SUMMARY
from vmn_exp.core.status import (
    load_run_state,
    run_state_observed_at,
    status_fields,
)
from vmn_exp.core.tree import children_by_parent, fleet_summary, run_status, subtree_verstrs
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.detail_env import detail_env, env_file
from vmn_exp.ui.readers.detail_reads import RunStates, submit
from vmn_exp.ui.readers.failure_context import failure_fields
from vmn_exp.ui.readers.histograms import detail_media
from vmn_exp.ui.readers.object_series import object_series, readable, x_of
from vmn_exp.ui.readers.parsed_logs import LogSnapshot, ParsedLogs
from vmn_exp.ui.readers.patches import patch_presence
from vmn_exp.ui.readers.range_series import range_series
from vmn_exp.ui.readers.series import DEFAULT_MAX_POINTS, points_per_metric

from vmn_exp.snapshot import _resolve_verstr

LOG_TAIL = 200


_DETAIL_STATUS_KEYS = tuple(status_fields(None)) + (
    "parent",
    "children",
    "kind",
    "depth",
    "tree_status",
    "sweep_planned",
    "sweep_trials",
    "last_metric_at",
    "fleet",
    "error",
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


def _full_error(storage, app_name, verstr, run_state):
    """The run's whole ``error``: the index keeps only its summary
    (``slim_run_state``), so a failed run's state is read from storage."""
    if not run_state or ERROR_SUMMARY not in run_state:
        return (run_state or {}).get("error")
    return (load_run_state(storage, app_name, verstr) or {}).get("error")


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
    job_status=None,
):
    """Status payload with the run's place in the tree.

    Reads the run state of the subtree only; *metadata* and *log* (a list or
    a :class:`LogSnapshot`) come from the caller, which already loaded both.
    *edges* is a ``(storage, app_name) -> {verstr: parent}`` provider; it
    should hand back the same mapping while nothing changed, which makes the
    tree lookup a dict lookup. *read_observed_at* gives each member's
    run_state.yml store write time, which stuck detection weighs too.
    *job_status(verstr)* gives a job's tree fields and ``fleet`` from its
    rollup (None for a run without children): a job then reads its own run
    state only.
    """
    job = job_status(verstr) if job_status else None
    if job is not None:
        return _job_detail(storage, app_name, verstr, metadata, log, job,
                           read_run_state, read_observed_at)
    edges_of = edges(storage, app_name)
    parent_of = edges_of
    if verstr not in edges_of:  # not indexed yet: overlay, never copy the rest
        parent_of = ChainMap({verstr: metadata.get("parent")}, edges_of)
    children_of = _children_of(edges_of)
    own_state = read_run_state(storage, app_name, verstr)
    read_state_fn = lambda v: (  # noqa: E731
        own_state if v == verstr else read_run_state(storage, app_name, v)
    )
    observed_at_fn = lambda v: read_observed_at(storage, app_name, v)  # noqa: E731
    detail = run_status(
        verstr,
        parent_of,
        read_state_fn,
        observed_at=observed_at_fn,
        children_of=children_of,
        row_of=read_child_row,
    )
    detail["parent"] = metadata.get("parent")
    detail["error"] = _full_error(storage, app_name, verstr, own_state)
    detail["last_metric_at"] = _last_metric_at(log)

    if detail.get("kind") == "outer":
        expected = None
        if isinstance(log, LogSnapshot):
            ep = log.params.get("expected_pods")
            if isinstance(ep, (int, float)):
                expected = int(ep)
        if expected is None:
            expected = detail.get("sweep_planned")
        fleet = fleet_summary(
            verstr, children_of, read_state_fn,
            observed_at=observed_at_fn, expected=expected,
        )
        detail["fleet"] = fleet and {k: v for k, v in fleet.items() if k != "children"}
    else:
        detail["fleet"] = None

    return {k: detail.get(k) for k in _DETAIL_STATUS_KEYS}


def _job_detail(storage, app_name, verstr, metadata, log, job, read_run_state,
                read_observed_at):
    own_state = read_run_state(storage, app_name, verstr)
    detail = status_fields(own_state, observed_at=read_observed_at(storage, app_name, verstr))
    detail.update(job, parent=metadata.get("parent"),
                  error=_full_error(storage, app_name, verstr, own_state),
                  last_metric_at=_last_metric_at(log))
    return {k: detail.get(k) for k in _DETAIL_STATUS_KEYS}


def _last_metric_at(log):
    return log.last_metric_at if isinstance(log, LogSnapshot) else last_metric_at(log)


def _resolve_name(storage, app_name, verstr_ref, resolve=None):
    """``(verstr, error)`` for a ref.

    *resolve* (``ref -> (verstr, error)``, e.g. an index snapshot's) is tried
    first; storage answers what it cannot, such as a run it has not seen yet.
    """
    if resolve:
        verstr, err = resolve(verstr_ref)
    if not resolve or err:
        verstr, err = _resolve_verstr(storage, app_name, verstr_ref, kind="experiment")
    return (None, err) if err else (verstr, None)


def _found(verstr, metadata):
    """``(metadata, error)``: a run without metadata is not found."""
    if metadata is None:
        return None, RefError(f"Experiment {verstr} not found")
    return metadata, None


def _resolve(storage, app_name, verstr_ref, resolve=None):
    """``(verstr, metadata, error)`` for a ref, loading metadata only."""
    verstr, err = _resolve_name(storage, app_name, verstr_ref, resolve)
    if err:
        return None, None, err
    metadata, err = _found(verstr, storage.load_metadata(app_name, verstr))
    return (None, None, err) if err else (verstr, metadata, None)


def _status_members(storage, app_name, verstr, edges, job):
    """The runs whose states the status detail reads: a job's own, else its
    subtree's (from the index edges)."""
    if job is not None:
        return [verstr]
    return subtree_verstrs(verstr, _children_of(edges(storage, app_name)))


def _once(fn):
    """*fn(verstr)*, its answer kept for the request."""
    if fn is None:
        return None
    answers = {}

    def call(verstr):
        if verstr not in answers:
            answers[verstr] = fn(verstr)
        return answers[verstr]

    return call


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
    step_range=None,
    last_good=None,
    job_status=None,
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
    the run's and the *schema*'s summary policies. *step_range* (``(lo, hi)``)
    keeps that range of each series, read from the metric objects (see
    :mod:`~vmn_exp.ui.readers.range_series`); ``compacted`` tells whether
    every metrics writer of the run has its ``.vmx``. ``idx`` / ``name`` come
    from the resolved run's index row (*read_child_row*); ``idx`` is None
    without it. A failed or stuck run adds ``output_tail``/``last_step``/
    ``last_good`` (:mod:`~vmn_exp.ui.readers.failure_context`; *last_good*
    is ``verstr -> {verstr, idx, name} | None``). *job_status*: see
    :func:`status_detail`.
    """
    verstr, err = _resolve_name(storage, app_name, verstr_ref, resolve)
    if err:
        return None, err
    edges = edges or _placement_edges
    job_status = _once(job_status)
    # Every read below is independent of the others: all in flight at once.
    metadata_read = submit(storage.load_metadata, app_name, verstr)
    log_read = submit(_PARSED.get, storage, app_name, verstr, read_log)
    artifacts_read = submit(list_artifacts, storage, app_name, verstr)
    env_read = submit(env_file, storage, app_name, verstr)
    compacted_read = submit(record_compacted, storage, app_name, verstr)
    states = RunStates(storage, app_name, read_run_state, read_observed_at)
    states.prefetch(_status_members(
        storage, app_name, verstr, edges, job_status(verstr) if job_status else None))

    metadata, err = _found(verstr, metadata_read.result())
    if err:
        return None, err
    snapshot = log_read.result()
    tail = snapshot.tail(LOG_TAIL)
    series, series_total = {}, {}
    if include_series and step_range is not None:
        # On this thread: range_series waits on the read pool itself.
        series, series_total, _ = range_series(
            storage, app_name, verstr, keys, max_points, None, step_range, schema
        )
    elif include_series:
        series, series_total = thinned_series(snapshot, keys, max_points, x=x)
    metrics, metric_summary = snapshot.summarized_metrics(schema)
    row = (read_child_row(verstr) if read_child_row else None) or {}
    detail = {
        "metadata": metadata,
        "idx": row.get("idx"),
        "name": row.get("name") or metadata.get("name"),
        "log": snapshot.log() if include_log else tail,
        "log_tail": tail,
        "log_total": snapshot.total,
        "params": snapshot.params,
        "metrics": metrics,
        "metric_summary": metric_summary,
        "series": series,
        "series_total": series_total,
        "step_metrics": snapshot.step_metrics(schema),
        "hidden_metrics": snapshot.hidden_metrics(schema),
        "artifacts": artifacts_read.result(),
        **detail_media(snapshot.media),
        "status": status_detail(
            storage,
            app_name,
            verstr,
            metadata,
            snapshot,
            edges,
            read_run_state=states.read_run_state,
            read_observed_at=states.read_observed_at,
            read_child_row=read_child_row,
            job_status=job_status,
        ),
        "patches": patch_presence(storage, app_name, verstr, metadata),
        "env": detail_env(storage, app_name, verstr, env_read.result(), metadata),
        "inputs": fold_inputs_dict(snapshot._parsed.fold) or None,
        "outputs": fold_outputs_dict(snapshot._parsed.fold) or None,
        "imported_from": metadata.get("imported_from"),
        "forked_from": metadata.get("forked_from"),
        "rerun_of": metadata.get("rerun_of"),
        "rewinds": snapshot.rewinds(),
        "compacted": compacted_read.result(),
    }
    detail.update(failure_fields(storage, app_name, verstr, detail, snapshot, last_good))
    return detail, None


_THINNED_PER_SNAPSHOT = 4


def thinned_series(snapshot, keys, max_points, budget=None, x=None):
    """``(series, series_total)`` of *keys* (None: all), thinned so they stay
    within *budget* points in all (default: the per-response cap). With *x*
    (see :func:`~vmn_exp.ui.readers.object_series.x_of`) those metrics are
    joined on their x metric first.
    Memoized on the snapshot, so an unchanged run's poll does not thin again."""
    known = snapshot.series_keys()
    names = list(known) if keys is None else [k for k in keys if k in known]
    if isinstance(x, str):
        names = [k for k in names if k != x]
    joins = x_of(names, x)
    per_metric = points_per_metric(max_points, len(names), budget)
    memo_key = (tuple(names), per_metric, tuple(sorted(joins.items())))
    hit = snapshot.memo.get(memo_key)
    if hit is None:
        hit = _thin(snapshot, names, joins, per_metric)
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


def run_series(
    storage, app_name, verstr, keys=None, max_points=DEFAULT_MAX_POINTS, budget=None,
    x=None, schema=None,
):
    """``(series, series_total, step_metrics)`` of an existing run, or None
    when it is gone — read from its metric objects when the storage lists
    them, else from its parsed log."""
    if readable(storage):
        return object_series(storage, app_name, verstr, keys, max_points, budget, x, schema)
    if storage.load_metadata(app_name, verstr) is None:
        return None
    snapshot = _PARSED.get(storage, app_name, verstr, _load_log)
    series, totals = thinned_series(snapshot, keys, max_points, budget, x)
    return series, totals, snapshot.step_metrics(schema)


def run_media(storage, app_name, verstr):
    """The media view (every histogram's served steps) of an existing run, or
    None when it is gone."""
    if storage.load_metadata(app_name, verstr) is None:
        return None
    return _PARSED.get(storage, app_name, verstr, _load_log).media


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
