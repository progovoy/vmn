#!/usr/bin/env python3
"""Experiment references resolved through the experiment index.

``latest``, ``@N`` and a dev-verstr prefix all need the app's full list of
runs. The storage walk (:func:`~version_stamp.cli.snapshot._resolve_verstr`)
parses every record's metadata for it; the index already holds those rows and
re-reads only what changed. An exact verstr or a stamped version needs no list
at all and never touches the index. Results and error strings are the walk's;
if the index is unavailable, the walk answers.

Imports only ``core`` and the snapshot helpers, so ``version_stamp.exp`` can
use it too.
"""
import logging

from version_stamp.cli.snapshot import _resolve_verstr
from version_stamp.core import experiment_index

KIND = "experiment"
_LATEST_WORDS = ("latest", "@latest")
_LOGGER = logging.getLogger(__name__)


def index_snapshot(storage, app_name):
    """The app's up-to-date :class:`IndexSnapshot`, or None if the index fails."""
    try:
        index = experiment_index.shared_index(storage, app_name)
        return index.refresh_if_stale(0)
    except Exception:
        _LOGGER.debug("Experiment index unavailable", exc_info=True)
        return None


def _needs_listing(storage, app_name, ref, latest):
    if latest or ref in _LATEST_WORDS:
        return True
    if ref is None:
        return False
    if ref.startswith("@"):
        return True
    return "-dev." in ref and not storage.exists(app_name, ref)


def resolve_experiment(storage, app_name, ref, latest=False, snapshot=None):
    """``(verstr, error)`` for *ref*, like ``_resolve_verstr(kind="experiment")``.

    *snapshot* is an :class:`IndexSnapshot` the caller already holds.
    """
    if not _needs_listing(storage, app_name, ref, latest):
        return ref, None
    snapshot = snapshot or index_snapshot(storage, app_name)
    if snapshot is None:
        return _resolve_verstr(storage, app_name, ref, latest=latest, kind=KIND)
    return snapshot.resolve(ref, latest=latest, kind=KIND)


def parent_edges(storage, app_name, snapshot=None):
    """``{verstr: parent}`` for every run of the app."""
    snapshot = snapshot or index_snapshot(storage, app_name)
    if snapshot is not None:
        return dict(snapshot.edges)
    return {m["verstr"]: m.get("parent") for m in storage.list_snapshots(app_name)}


def storage_index(storage, app_name, verstr, snapshot=None):
    """The 1-based storage index (what ``@N`` resolves) of *verstr*, or None."""
    snapshot = snapshot or index_snapshot(storage, app_name)
    if snapshot is not None:
        row = snapshot.row(verstr)
        return row["idx"] if row else None
    metas = storage.list_snapshots(app_name)
    return next((i for i, m in enumerate(metas, 1) if m["verstr"] == verstr), None)


def recent_verstrs(storage, app_name, count):
    """The *count* most recent runs' verstrs in storage order."""
    snapshot = index_snapshot(storage, app_name)
    if snapshot is not None:
        return [row["verstr"] for row in snapshot.rows[-count:]]
    return [m["verstr"] for m in storage.list_snapshots(app_name)[-count:]]
