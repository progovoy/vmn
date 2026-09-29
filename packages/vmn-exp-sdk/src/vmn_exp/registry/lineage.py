"""Lineage joined with the registry.

* :func:`run_lineage` — a run's lineage (:func:`vmn_exp.core.lineage.resolve_lineage`)
  with its upstream links naming the registered versions they used, its
  ``vmn-registry://`` inputs in ``datasets`` and the versions registered
  from it in ``models``.
* :func:`version_lineage` — a version's producer run (its ``run_ref``) and
  the runs recorded using it (the ``<name>-uses`` record), each a lineage
  node whose ``found`` says whether the run is still there.

*index_for(app)* returns an app's :class:`~vmn_exp.core.lineage.LineageIndex`;
:func:`app_indexes` builds them from the storage's experiment index.
"""
from __future__ import annotations

import vmn_exp.core.index as experiment_index
from vmn_exp.core.lineage import DEFAULT_LIMIT, LineageIndex, resolve_lineage, run_node
from vmn_exp.core.tree import annotate_rows
from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries, read_uses
from vmn_exp.registry.store import get_version, model_kind, run_of
from vmn_exp.registry.view import models_for_run, run_models


class RegistryLinks:
    """The registry lookups :func:`resolve_lineage` takes as *registry*: the
    registry's run → versions map is read once per walk, not once per node."""

    def __init__(self, storage):
        self.storage = storage
        self._run_models = None

    def models_of(self, app, verstr):
        if self._run_models is None:
            self._run_models = run_models(self.storage)
        return self._run_models.get((app, verstr), ())

    def version_live(self, name, n):
        status = _version_status(self.storage, name, n)
        return status != "deleted" and get_version(self.storage, name, n) is not None


def _version_status(storage, name, n):
    return fold_registry(read_entries(storage, name))["status"].get(n, "active")


def app_indexes(storage):
    """``index_for(app)`` over *storage*'s status-annotated index rows,
    each app's index built once."""
    indexes = {}

    def index_for(app):
        if app not in indexes:
            rows, states, observed = experiment_index.indexed_status_rows(storage, app)
            indexes[app] = LineageIndex(annotate_rows(rows, states, observed))
        return indexes[app]

    return index_for


def run_lineage(
    storage, app_name, verstr, index_for, *, depth=1, limit=DEFAULT_LIMIT, status_of=None
):
    """``{"app", "verstr", "upstream", "downstream", "datasets", "models",
    "truncated"}`` of run *verstr*. Raises KeyError when the run is unknown."""
    found = resolve_lineage(
        app_name, verstr, index_for, depth=depth, limit=limit, status_of=status_of,
        registry=RegistryLinks(storage),
    )
    found.update(app=app_name, verstr=verstr, models=models_for_run(storage, app_name, verstr))
    return found


def version_lineage(storage, name, n, index_for=None, status_of=None):
    """``{"model", "version", "kind", "status", "producer", "consumers"}`` of
    version *n* of *name* — deleted versions too. *producer* is None for a
    reference dataset; *consumers* are in first-use order. Raises KeyError
    when the version does not exist."""
    meta = get_version(storage, name, n)
    if meta is None:
        raise KeyError(f"Version {n} of {name!r} does not exist")
    index_for = index_for or app_indexes(storage)
    producer = run_of(meta)
    uses = read_uses(storage, name).get(n, [])
    return {
        "model": name,
        "version": n,
        "kind": model_kind(storage, name) or "model",
        "status": _version_status(storage, name, n),
        "producer": run_node(producer, index_for, status_of=status_of) if producer else None,
        "consumers": [
            run_node((use["app"], use["verstr"]), index_for, status_of=status_of)
            for use in uses
        ],
    }
