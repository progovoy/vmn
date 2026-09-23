#!/usr/bin/env python3
"""One experiment's detail for the vmn ui API, bounded however long it ran.

A run page polls this while the run is live, so its cost must not grow with the
log or with the workspace: the log is returned as a tail (the rest is paged via
:func:`log_page`), every metric series is thinned to a chart's worth of points,
patch presence comes from the metadata flags instead of the tarball, and the
run tree is answered from parent edges that are cached across polls. The parsed
log of an unchanged run is reused across polls and log pages.
"""
import threading
from collections import OrderedDict

from version_stamp.cli.snapshot import _resolve_verstr
from version_stamp.core.experiment_log import (
    effective_params,
    last_metric_at,
    latest_metrics,
    list_artifacts,
    metric_series,
)
from version_stamp.core.experiment_log import load_log as _load_log
from version_stamp.core.experiment_status import load_run_state, status_fields
from version_stamp.core.experiment_tree import subtree_status
from version_stamp.ui.readers.series import DEFAULT_MAX_POINTS, downsample_series
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
            known = self._by_app.get(app_name, {})
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


class ParsedLogs:
    """Parsed log + full series per record, reused while its log files are
    unchanged. Bounded LRU; a backend without cheap ``record_files`` (reads
    that merge a remote) is simply never cached."""

    def __init__(self, size=32):
        self._size = size
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get(self, storage, app_name, verstr, read_log):
        """``(log, series)`` for the record, reading it only when it changed."""
        sig = _log_signature(storage, app_name, verstr)
        key = (_identity(storage), app_name, verstr)
        with self._lock:
            hit = self._entries.get(key)
            if sig is not None and hit and hit[0] == sig:
                self._entries.move_to_end(key)
                return hit[1], hit[2]
        log = read_log(storage, app_name, verstr)
        series = metric_series(log)
        if sig is not None:
            with self._lock:
                self._entries[key] = (sig, log, series)
                self._entries.move_to_end(key)
                while len(self._entries) > self._size:
                    self._entries.popitem(last=False)
        return log, series


def _identity(storage):
    identity_of = getattr(storage, "cache_identity", None)
    return (identity_of() if identity_of else None) or id(storage)


def _log_signature(storage, app_name, verstr):
    """The record's log files' ``(size, mtime...)``, or None when unknown."""
    record_files = getattr(storage, "record_files", None)
    files = record_files(app_name, verstr) if record_files else None
    if files is None:
        return None
    return tuple(sorted((n, tuple(sig)) for n, sig in files.items() if n.startswith("log.")))


_PARSED = ParsedLogs()


def status_detail(
    storage, app_name, verstr, metadata, log, edges, read_run_state=load_run_state
):
    """Status payload with the run's place in the tree.

    Reads the run state of the subtree only; *metadata* and *log* come from the
    caller, which already loaded both.
    """
    parent_of = dict(edges(storage, app_name))
    parent_of.setdefault(verstr, metadata.get("parent"))
    run_state, tree = subtree_status(
        verstr, parent_of, lambda v: read_run_state(storage, app_name, v)
    )
    detail = status_fields(run_state)
    detail.update(tree)
    detail["parent"] = metadata.get("parent")
    detail["last_metric_at"] = last_metric_at(log)
    return {k: detail.get(k) for k in _DETAIL_STATUS_KEYS}


def _resolve(storage, app_name, verstr_ref):
    """``(verstr, metadata, error)`` for a ref, loading metadata only."""
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
):
    """``(detail, error)``; the ref supports @N / prefix / 'latest'.

    ``log`` is the tail unless *include_log*; ``log_tail`` / ``log_total`` and
    ``series_total`` let a client page the log and label thinned charts.
    *read_log* / *read_run_state* are the reader's own loaders.
    """
    verstr, metadata, err = _resolve(storage, app_name, verstr_ref)
    if err:
        return None, err

    log, full_series = _PARSED.get(storage, app_name, verstr, read_log)
    tail = log[-LOG_TAIL:]
    series, series_total = downsample_series(full_series, max_points)
    return {
        "metadata": metadata,
        "log": log if include_log else tail,
        "log_tail": tail,
        "log_total": len(log),
        "params": effective_params(log),
        "metrics": latest_metrics(log),
        "series": series,
        "series_total": series_total,
        "artifacts": list_artifacts(storage, app_name, verstr),
        "status": status_detail(
            storage,
            app_name,
            verstr,
            metadata,
            log,
            edges or ParentEdges(),
            read_run_state=read_run_state,
        ),
        "patches": _patch_presence(storage, app_name, verstr, metadata),
    }, None


def log_page(storage, app_name, verstr_ref, offset=0, limit=LOG_TAIL, read_log=_load_log):
    """``({"entries", "total"}, error)`` — a slice of the log, oldest first."""
    verstr, _, err = _resolve(storage, app_name, verstr_ref)
    if err:
        return None, err
    log, _ = _PARSED.get(storage, app_name, verstr, read_log)
    offset = max(int(offset), 0)
    return {"entries": log[offset : offset + max(int(limit), 0)], "total": len(log)}, None
