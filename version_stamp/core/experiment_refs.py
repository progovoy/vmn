#!/usr/bin/env python3
"""Experiment references and placement through the experiment index.

``latest``, ``@N`` and a dev-verstr prefix need the app's full list of runs,
and a run's place in the tree needs every parent edge. The index already holds
both and re-reads only what changed, where walking storage parses every
record's metadata. An exact verstr or a stamped version needs no list at all
and never touches the index. Resolution goes through
:meth:`IndexSnapshot.resolve`, which matches the CLI's ``_resolve_verstr``
results and error strings; if the index is unavailable, a snapshot built from
a metadata-only listing answers instead.

Storage is duck-typed; like the rest of ``core`` this imports nothing from
``cli``, ``ui`` or ``exp``.
"""

from version_stamp.core import experiment_index
from version_stamp.core.experiment_index_snapshot import IndexSnapshot
from version_stamp.core.logging import VMN_LOGGER

KIND = "experiment"
_LATEST_WORDS = ("latest", "@latest")


def _listed_snapshot(storage, app_name):
    """An :class:`IndexSnapshot` of placement fields only, from a metadata-only
    listing — the fallback when the index is unavailable."""
    rows = [
        {
            "idx": idx,
            "verstr": meta["verstr"],
            "timestamp": meta.get("timestamp"),
            "parent": meta.get("parent"),
        }
        for idx, meta in enumerate(storage.list_snapshots(app_name), 1)
    ]
    return IndexSnapshot.build(app_name, 0, rows, {})


def placement_snapshot(storage, app_name, snapshot=None):
    """*snapshot*, else the index's, else one built from a metadata-only listing."""
    return snapshot or experiment_index.indexed_snapshot(
        storage, app_name, fallback=_listed_snapshot
    )


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
    snapshot = placement_snapshot(storage, app_name, snapshot)
    return snapshot.resolve(ref, latest=latest, kind=KIND)



def resolve_parent(storage, app_name, explicit=None, env_ref=None):
    """Parent verstr for a new experiment: ``(parent, error_code)``.

    *explicit* (``--parent``) wins over *env_ref* (the ``VMN_EXPERIMENT_ID`` an
    enclosing run exported). Both are resolved against storage, so a parent is
    only ever recorded if it exists. An unresolvable explicit ref is a hard
    error; a stale env ref is dropped with a warning — the outer run may simply
    have been pruned, which is no reason to fail this one.
    """
    ref = explicit or env_ref
    if not ref:
        return None, None

    verstr, err = resolve_experiment(storage, app_name, ref)
    if not err:
        return verstr, None
    if explicit:
        VMN_LOGGER.error(err)
        return None, 1
    VMN_LOGGER.warning(f"Ignoring stale VMN_EXPERIMENT_ID '{ref}': {err}")
    return None, None


def parent_edges(storage, app_name, snapshot=None):
    """``{verstr: parent}`` for every run of the app."""
    return dict(placement_snapshot(storage, app_name, snapshot).edges)


def storage_index(storage, app_name, verstr, snapshot=None):
    """The 1-based storage index (what ``@N`` resolves) of *verstr*, or None."""
    row = placement_snapshot(storage, app_name, snapshot).row(verstr)
    return row["idx"] if row else None


def recent_verstrs(storage, app_name, count):
    """The *count* most recent runs' verstrs in storage order."""
    rows = placement_snapshot(storage, app_name).rows
    return [row["verstr"] for row in rows[-count:]]
