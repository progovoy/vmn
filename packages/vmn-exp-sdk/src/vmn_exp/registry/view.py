"""Registry read views: model state, ref resolution, and registered-run enumeration.

Public surface
--------------
model_state(storage, model) -> dict
    Full model snapshot: header, per-version rows with status and aliases,
    top-level alias map, and ordered audit log.

resolve_ref(storage, ref) -> dict
    Resolve ``model@alias``, ``model@N``, ``model@latest``, or bare ``model``
    to its version metadata dict.  Raises ``KeyError`` for deleted versions
    or unknown aliases (error message lists available aliases).

registered_runs(storage) -> set[tuple[str, str]]
    Set of ``(app, verstr)`` pairs referenced by any non-deleted version of
    any model — used by prune to refuse deletion of registered runs.

models_for_run(storage, app, verstr) -> list[dict]
    The live model versions registered from one run (run lineage).

Both read one ``{(app, verstr): versions}`` map, rebuilt only when the
registry's file listing changes.
"""
from __future__ import annotations

import threading
import weakref

from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries
from vmn_exp.registry.names import (
    HEADER_RECORD,
    parse_ref,
    parse_version_record,
)
from vmn_exp.registry.store import (
    get_version,
    header_kind,
    list_models,
    load_header,
    list_versions,
    model_kind,
    registry_storage,
    run_of,
)


_VERSION_ROW_FIELDS = ("run_ref", "artifact_path", "uri", "digest", "size", "files")


def model_state(storage, model: str) -> dict:
    """Return a full snapshot of *model* in *storage*.

    Returns::

        {
            "header":   metadata dict from ensure_model,
            "kind":     "model" | "dataset" (None without a header),
            "versions": [
                {"n": int, "run_ref": ..., "artifact_path": ..., "uri": ...,
                 "digest": ..., "size": ..., "files": ...,
                 "status": str, "aliases": [str]},
                ...
            ],
            "aliases":  {alias: version_number},
            "audit":    [entries ordered by (ts, writer, pos)],
        }
    """
    header = load_header(storage, model)

    entries = read_entries(storage, model)
    fold = fold_registry(entries)

    # Reverse alias map: version_number -> [alias, ...]
    alias_by_version: dict = {}
    for alias, n in fold["aliases"].items():
        alias_by_version.setdefault(n, []).append(alias)

    versions = []
    for n in list_versions(storage, model):
        meta = get_version(storage, model, n) or {}
        versions.append({
            "n": n,
            **{field: meta.get(field) for field in _VERSION_ROW_FIELDS},
            "status": fold["status"].get(n, "active"),
            "aliases": sorted(alias_by_version.get(n, [])),
        })

    return {
        "header": header,
        "kind": header_kind(header),
        "versions": versions,
        "aliases": fold["aliases"],
        "audit": fold["audit"],
    }


def resolve_ref(storage, ref: str) -> dict:
    """Resolve *ref* to a version metadata dict.

    Supported forms: ``model@alias``, ``model@3``, ``model@latest``, ``model``.

    Raises ``KeyError`` when:
    - the alias does not exist (message lists available aliases);
    - the resolved version is deleted;
    - the version number does not exist.
    """
    model, kind, value = parse_ref(ref)

    entries = read_entries(storage, model)
    fold = fold_registry(entries)

    if kind == "alias":
        alias = value
        if alias not in fold["aliases"]:
            available = sorted(fold["aliases"].keys())
            raise KeyError(
                f"Alias {alias!r} not found for model {model!r}. "
                f"Available aliases: {available}"
            )
        n = fold["aliases"][alias]
        return _version_or_raise(storage, model, n, fold, ref)

    if kind == "version":
        return _version_or_raise(storage, model, value, fold, ref)

    # kind == "latest": highest non-deleted version number
    non_deleted = [
        n for n in list_versions(storage, model)
        if fold["status"].get(n) != "deleted"
    ]
    if not non_deleted:
        raise KeyError(f"No non-deleted versions found for model {model!r}")
    return _version_or_raise(storage, model, max(non_deleted), fold, ref)


def registered_runs(storage) -> set:
    """Return ``{(app, verstr), ...}`` for all non-deleted registered versions.

    The prune command uses this to prevent deleting experiment runs that a
    model version still references.
    """
    return set(_run_models(storage))


def models_for_run(storage, app: str, verstr: str) -> list:
    """``[{model, kind, version, aliases, status, artifact_path}]`` registered from
    run *verstr* of *app* (deleted versions left out), model/version-ordered."""
    return [dict(m) for m in _run_models(storage).get((app, verstr), ())]


def run_models(storage) -> dict:
    """``{(app, verstr): [version entry]}`` of every run with live versions
    (shared cache: read, never mutate)."""
    return _run_models(storage)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RUN_MODELS = weakref.WeakKeyDictionary()  # storage -> (listing, run models)
_RUN_MODELS_LOCK = threading.Lock()


def _run_models(storage):
    """``{(app, verstr): [version entry]}``, cached on the registry listing.

    The key holds only the records the scan reads (model headers and
    versions): a write to any other record, like a usage log, is no rescan."""
    reg = registry_storage(storage)
    listing = {
        (model, name): files
        for model in reg.list_apps()
        for name, files in reg.list_files(model).items()
        if name == HEADER_RECORD or parse_version_record(name)
    }
    with _RUN_MODELS_LOCK:
        cached = _RUN_MODELS.get(storage)
    if listing and cached is not None and cached[0] == listing:
        return cached[1]
    run_models = _scan_run_models(storage)
    if listing:
        with _RUN_MODELS_LOCK:
            _RUN_MODELS[storage] = (listing, run_models)
    return run_models


def _scan_run_models(storage):
    run_models = {}
    for model, kind, n, meta, fold in _live_versions(storage):
        run = run_of(meta)
        if run is None:
            continue
        run_models.setdefault(run, []).append({
            "model": model,
            "kind": kind,
            "version": n,
            "aliases": sorted(a for a, v in fold["aliases"].items() if v == n),
            "status": fold["status"].get(n, "active"),
            "artifact_path": meta.get("artifact_path"),
        })
    return run_models


def _live_versions(storage):
    """``(model, kind, n, version metadata, registry fold)`` of every non-deleted version."""
    for model in list_models(storage):
        kind = model_kind(storage, model)
        fold = fold_registry(read_entries(storage, model))
        for n in list_versions(storage, model):
            if fold["status"].get(n) == "deleted":
                continue
            meta = get_version(storage, model, n)
            if meta:
                yield model, kind, n, meta, fold


def _version_or_raise(storage, model: str, n: int, fold: dict, ref: str) -> dict:
    if fold["status"].get(n) == "deleted":
        raise KeyError(
            f"Version {n} of model {model!r} is deleted (ref={ref!r})"
        )
    meta = get_version(storage, model, n)
    if meta is None:
        raise KeyError(
            f"Version {n} of model {model!r} does not exist (ref={ref!r})"
        )
    return meta
