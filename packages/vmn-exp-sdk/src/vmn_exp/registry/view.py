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
"""
from __future__ import annotations

from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries
from vmn_exp.registry.names import REGISTRY_APP, parse_ref
from vmn_exp.registry.store import get_version, list_models, list_versions


def model_state(storage, model: str) -> dict:
    """Return a full snapshot of *model* in *storage*.

    Returns::

        {
            "header":   metadata dict from ensure_model,
            "versions": [
                {"n": int, "run_ref": ..., "artifact_path": ...,
                 "status": str, "aliases": [str]},
                ...
            ],
            "aliases":  {alias: version_number},
            "audit":    [entries ordered by (ts, writer, pos)],
        }
    """
    header, _ = storage.load(REGISTRY_APP, model)

    entries = read_entries(storage, model)
    fold = fold_registry(entries)

    # Reverse alias map: version_number -> [alias, ...]
    alias_by_version: dict = {}
    for alias, n in fold["aliases"].items():
        alias_by_version.setdefault(n, []).append(alias)

    versions = []
    for n in list_versions(storage, model):
        meta = get_version(storage, model, n)
        versions.append({
            "n": n,
            "run_ref": meta.get("run_ref") if meta else None,
            "artifact_path": meta.get("artifact_path") if meta else None,
            "status": fold["status"].get(n, "active"),
            "aliases": sorted(alias_by_version.get(n, [])),
        })

    return {
        "header": header,
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
    result: set = set()
    for _, _, meta, _ in _live_versions(storage):
        run_ref = meta.get("run_ref")
        if isinstance(run_ref, dict):
            app = run_ref.get("app")
            verstr = run_ref.get("verstr")
            if app and verstr:
                result.add((app, verstr))
    return result


def models_for_run(storage, app: str, verstr: str) -> list:
    """``[{model, version, aliases, status, artifact_path}]`` registered from
    run *verstr* of *app* (deleted versions left out), model/version-ordered."""
    found = []
    for model, n, meta, fold in _live_versions(storage):
        if meta.get("run_ref") != {"app": app, "verstr": verstr}:
            continue
        found.append({
            "model": model,
            "version": n,
            "aliases": sorted(a for a, v in fold["aliases"].items() if v == n),
            "status": fold["status"].get(n, "active"),
            "artifact_path": meta.get("artifact_path"),
        })
    return found


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _live_versions(storage):
    """``(model, n, version metadata, registry fold)`` of every non-deleted version."""
    for model in list_models(storage):
        fold = fold_registry(read_entries(storage, model))
        for n in list_versions(storage, model):
            if fold["status"].get(n) == "deleted":
                continue
            meta = get_version(storage, model, n)
            if meta:
                yield model, n, meta, fold


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
