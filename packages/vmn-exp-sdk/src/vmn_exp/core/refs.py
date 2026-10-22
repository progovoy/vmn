#!/usr/bin/env python3
"""Experiment references and placement through the experiment index.

``latest``, ``@N`` and a dev-verstr prefix need the app's full list of runs,
and a run's place in the tree needs every parent edge. The index already holds
both and re-reads only what changed, where walking storage parses every
record's metadata. An exact verstr or a stamped version needs no list at all
and never touches the index. Once the app is indexed, resolving and placing
one run are point reads on the persisted index (:func:`point_placement`, plan
25 F1); otherwise resolution goes through :meth:`IndexSnapshot.resolve`. Both
match the CLI's ``_resolve_verstr`` results and error strings; if the index is
unavailable, a snapshot built from a metadata-only listing answers instead.

Storage is duck-typed; like the rest of ``core`` this imports nothing from
``cli``, ``ui`` or ``exp``.
"""

import vmn_exp.core.index as experiment_index
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.direct_placement import direct_placement
from vmn_exp.core.index_point import point_view
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.resolve_ref import LATEST_WORDS

KIND = "experiment"


def _listed_snapshot(storage, app_name, schema):
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
    """*snapshot*, else the index's refreshed now (``latest`` right after a
    create resolves to it), else one built from a metadata-only listing."""
    return snapshot or experiment_index.indexed_snapshot(
        storage, app_name, wait=True, fallback=_listed_snapshot
    )


def point_placement(storage, app_name, snapshot=None, verstr=None):
    """*snapshot*, else a point view of the persisted index
    (:func:`~vmn_exp.core.index_point.point_view`), else, for an existing
    exact *verstr*, its own tree read from storage
    (:func:`~vmn_exp.core.direct_placement.direct_placement`), else
    :func:`placement_snapshot`'s. What it answers resolves a ref (``resolve``,
    not the direct one), gives a run's row (``row``) and its links
    (:func:`tree_links`)."""
    if snapshot is not None:
        return snapshot
    try:
        view = point_view(storage, app_name)
    except Exception:
        VMN_LOGGER.debug("Experiment index point read unavailable", exc_info=True)
        view = None
    if view is None and verstr is not None:
        view = direct_placement(storage, app_name, verstr)
    return view or placement_snapshot(storage, app_name)


def tree_links(placement, verstr=None, parent=None):
    """``(parent_of, children_of)`` lookups (``.get``) of a
    :func:`point_placement`; *verstr*'s *parent* stands in when the
    placement does not know the run."""
    parent_of = placement.parent_of
    if verstr is not None and placement.row(verstr) is None:
        parent_of = _Own(parent_of, verstr, parent)
    return parent_of, placement.children_of


class _Own:
    def __init__(self, links, verstr, parent):
        self._links, self._verstr, self._parent = links, verstr, parent

    def get(self, key, default=None):
        if key == self._verstr:
            return self._parent or default
        return self._links.get(key, default)


def _needs_listing(storage, app_name, ref, latest):
    if latest or ref in LATEST_WORDS:
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
    return point_placement(storage, app_name, snapshot).resolve(ref, latest=latest, kind=KIND)


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


def storage_index(storage, app_name, verstr, snapshot=None):
    """The 1-based storage index (what ``@N`` resolves) of *verstr*, or None."""
    row = point_placement(storage, app_name, snapshot).row(verstr)
    return row["idx"] if row else None


def recent_verstrs(storage, app_name, count):
    """The *count* most recent runs' verstrs in storage order."""
    rows = placement_snapshot(storage, app_name).rows
    return [row["verstr"] for row in rows[-count:]]
