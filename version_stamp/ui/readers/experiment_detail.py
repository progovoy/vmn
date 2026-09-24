#!/usr/bin/env python3
"""One experiment's detail for the vmn ui API, bounded however long it ran.

A run page polls this while the run is live, so its cost must not grow with the
log or with the workspace: the log is returned as a tail (the rest is paged via
:func:`log_page`), every metric series is thinned to a chart's worth of points,
patch presence comes from the metadata flags instead of the tarball, and the
run tree is answered from parent edges that are cached across polls. The parsed
log is reused across polls and log pages, and a grown local log costs only its
new bytes (:mod:`~version_stamp.ui.readers.parsed_logs`).
"""
import threading
from collections import ChainMap, OrderedDict

from version_stamp.cli.snapshot import _resolve_verstr
from version_stamp.core.experiment_log import last_metric_at, list_artifacts
from version_stamp.core.experiment_log import load_log as _load_log
from version_stamp.core.experiment_status import (
    load_run_state,
    run_state_observed_at,
    status_fields,
)
from version_stamp.core.experiment_tree import children_by_parent, run_status
from version_stamp.ui.readers.parsed_logs import LogSnapshot, ParsedLogs
from version_stamp.ui.readers.series import DEFAULT_MAX_POINTS, points_per_metric
from version_stamp.ui.readers.snapshots import _load_metadata, _patch_presence

LOG_TAIL = 200

_DETAIL_STATUS_KEYS = tuple(status_fields(None)) + (
    "parent",
    "children",
    "kind",
    "depth",
    "tree_status",
    "last_metric_at",
)


class ParentEdges:
    """``{verstr: parent}`` for an app's runs, kept across polls.

    A run's parent is written once, when the run is created, so only runs not
    seen before cost a metadata read; the listing itself is names only. Pruned
    runs drop out because they are no longer listed.
    """

    def __init__(self):
        self._by_app = {}
        self._lock = threading.Lock()

    def __call__(self, storage, app_name):
        names = storage.list_verstrs(app_name)
        with self._lock:
            known = self._by_app.get(app_name)
        if known is not None and len(known) == len(names) and all(v in known for v in names):
            return known  # the same mapping while unchanged: callers memoize on it
        known = known or {}
        edges = {}
        for verstr in names:
            if verstr in known:
                edges[verstr] = known[verstr]
            else:
                metadata = _load_metadata(storage, app_name, verstr) or {}
                edges[verstr] = metadata.get("parent")
        with self._lock:
            self._by_app[app_name] = edges
        return edges


class _ChildrenIndex:
    """``{parent: [child]}`` per edges mapping, rebuilt only for a new mapping.

    An edges provider returns the same mapping object while the edges are
    unchanged (and a new one when they change), so a poll costs a lookup.
    """

    def __init__(self, size=8):
        self._size = size
        self._by_id = OrderedDict()  # id -> (mapping, len, children_of)
        self._lock = threading.Lock()

    def __call__(self, parent_of):
        with self._lock:
            hit = self._by_id.get(id(parent_of))
            if hit and hit[0] is parent_of and hit[1] == len(parent_of):
                self._by_id.move_to_end(id(parent_of))
                return hit[2]
        children_of = children_by_parent(
            {"verstr": v, "parent": p} for v, p in parent_of.items()
        )
        with self._lock:
            self._by_id[id(parent_of)] = (parent_of, len(parent_of), children_of)
            while len(self._by_id) > self._size:
                self._by_id.popitem(last=False)
        return children_of


_CHILDREN = _ChildrenIndex()
_PARSED = ParsedLogs()


def status_detail(
    storage,
    app_name,
    verstr,
    metadata,
    log,
    edges,
    read_run_state=load_run_state,
    read_observed_at=run_state_observed_at,
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
    detail = run_status(
        verstr,
        parent_of,
        lambda v: read_run_state(storage, app_name, v),
        observed_at=lambda v: read_observed_at(storage, app_name, v),
        children_of=_CHILDREN(edges_of),
    )
    detail["parent"] = metadata.get("parent")
    detail["last_metric_at"] = (
        log.last_metric_at if isinstance(log, LogSnapshot) else last_metric_at(log)
    )
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
    metadata = _load_metadata(storage, app_name, verstr)
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
):
    """``(detail, error)``; the ref supports @N / prefix / 'latest'.

    ``log`` is the tail unless *include_log*; ``log_tail`` / ``log_total`` and
    ``series_total`` let a client page the log and label thinned charts.
    *keys* restricts ``series`` to those metrics; ``include_series=False``
    omits them. *read_log* / *read_run_state* are the reader's own loaders;
    *resolve* resolves the ref before storage is asked (see :func:`_resolve`);
    *read_observed_at* is the run-state store write time loader.
    """
    verstr, metadata, err = _resolve(storage, app_name, verstr_ref, resolve)
    if err:
        return None, err

    snapshot = _PARSED.get(storage, app_name, verstr, read_log)
    tail = snapshot.tail(LOG_TAIL)
    series, series_total = (
        thinned_series(snapshot, keys, max_points) if include_series else ({}, {})
    )
    return {
        "metadata": metadata,
        "log": snapshot.log() if include_log else tail,
        "log_tail": tail,
        "log_total": snapshot.total,
        "params": snapshot.params,
        "metrics": snapshot.metrics,
        "series": series,
        "series_total": series_total,
        "artifacts": list_artifacts(storage, app_name, verstr),
        "status": status_detail(
            storage,
            app_name,
            verstr,
            metadata,
            snapshot,
            edges or ParentEdges(),
            read_run_state=read_run_state,
            read_observed_at=read_observed_at,
        ),
        "patches": _patch_presence(storage, app_name, verstr, metadata),
    }, None


_THINNED_PER_SNAPSHOT = 4


def thinned_series(snapshot, keys, max_points, budget=None):
    """``(series, series_total)`` of *keys* (None: all), thinned so they stay
    within *budget* points in all (default: the per-response cap). Memoized on
    the snapshot, so an unchanged run's poll does not thin again."""
    known = snapshot.series_keys()
    names = list(known) if keys is None else [k for k in keys if k in known]
    per_metric = points_per_metric(max_points, len(names), budget)
    memo_key = (tuple(names), per_metric)
    hit = snapshot.memo.get(memo_key)
    if hit is None:
        hit = snapshot.thinned(names, per_metric)
        if len(snapshot.memo) >= _THINNED_PER_SNAPSHOT:
            snapshot.memo.clear()
        snapshot.memo[memo_key] = hit
    return hit


def run_series(
    storage, app_name, verstr, keys=None, max_points=DEFAULT_MAX_POINTS, budget=None
):
    """``(series, series_total)`` of an existing run, or None when it is gone."""
    if _load_metadata(storage, app_name, verstr) is None:
        return None
    snapshot = _PARSED.get(storage, app_name, verstr, _load_log)
    return thinned_series(snapshot, keys, max_points, budget)


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
