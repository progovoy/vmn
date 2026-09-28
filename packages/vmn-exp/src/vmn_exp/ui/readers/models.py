"""Read-side access to the model registry for the vmn-exp ui API.

Builds the TypeScript-contract shapes (ModelRow, ModelDetail) from the
lower-level registry API in vmn_exp.registry.
"""
from __future__ import annotations

from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries
from vmn_exp.registry.names import REGISTRY_APP
from vmn_exp.registry.store import get_version, list_models, list_versions


def _actor_str(actor) -> str:
    """Convert an actor dict or plain value to a display string."""
    if isinstance(actor, dict):
        return actor.get("writer") or actor.get("git_user_email") or "unknown"
    return str(actor) if actor else "unknown"


def _artifact_uri(storage, run: dict, artifact_path):
    if not artifact_path or not run["verstr"]:
        return None
    return storage.artifact_uri(run["app"], run["verstr"], artifact_path)


def _version_detail(storage, meta: dict, fold: dict, alias_by_version: dict, n: int) -> dict:
    """Build one ModelVersion dict from pre-loaded raw metadata."""
    run_ref = (meta or {}).get("run_ref")
    if isinstance(run_ref, dict):
        run = {"app": run_ref.get("app", ""), "verstr": run_ref.get("verstr", "")}
    elif isinstance(run_ref, str):
        run = {"app": "", "verstr": run_ref}
    else:
        run = {"app": "", "verstr": ""}

    artifact_path = (meta or {}).get("artifact_path")

    return {
        "version": n,
        "status": fold["status"].get(n, "active"),
        "run": run,
        "artifact_path": artifact_path,
        "artifact_uri": _artifact_uri(storage, run, artifact_path),
        "aliases": sorted(alias_by_version.get(n, [])),
        "created": (meta or {}).get("timestamp"),
        "description": (meta or {}).get("description"),
    }


def _build_audit(log_entries: list, version_metas: dict) -> list:
    """Build audit list from log entries.  Shape: AuditEntry[].

    *version_metas* maps version number → raw metadata dict (already loaded).
    """
    audit = []

    # Add a synthetic "register" entry for each version.
    for n, meta in sorted(version_metas.items()):
        actor = _actor_str((meta or {}).get("actor"))
        audit.append({
            "ts": (meta or {}).get("timestamp") or "",
            "actor": actor,
            "type": "register",
            "alias": None,
            "version": n,
            "status": None,
        })

    # Add alias / status entries from the log.
    for entry in log_entries:
        audit.append({
            "ts": entry.get("ts") or "",
            "actor": _actor_str(entry.get("actor")),
            "type": entry.get("type") or "",
            "alias": entry.get("alias"),
            "version": entry.get("version"),
            "status": entry.get("status"),
        })

    audit.sort(key=lambda e: e["ts"])
    return audit


def model_detail_response(storage, model_name: str) -> tuple:
    """Return ``(ModelDetail dict, None)`` or ``(None, error_message)``."""
    header, _ = storage.load(REGISTRY_APP, model_name)
    if header is None:
        return None, f"Model '{model_name}' not found"

    ns = list_versions(storage, model_name)
    entries = read_entries(storage, model_name)
    fold = fold_registry(entries)

    # Load each version's raw metadata once, reuse in both version list and audit.
    version_metas = {n: get_version(storage, model_name, n) for n in ns}

    alias_by_version: dict = {}
    for alias, ver_n in fold["aliases"].items():
        alias_by_version.setdefault(ver_n, []).append(alias)

    versions = [_version_detail(storage, version_metas[n], fold, alias_by_version, n) for n in ns]
    audit = _build_audit(fold["audit"], version_metas)

    return {
        "name": model_name,
        "description": header.get("description"),
        "versions": versions,
        "aliases": fold["aliases"],
        "audit": audit,
    }, None


def list_models_response(storage) -> dict:
    """Return ``{"models": [ModelRow ...]}`` for the list endpoint."""
    model_names = list_models(storage)
    rows = []
    for name in model_names:
        header, _ = storage.load(REGISTRY_APP, name)
        if header is None:
            continue
        ns = list_versions(storage, name)
        entries = read_entries(storage, name)
        fold = fold_registry(entries)

        latest = max(ns) if ns else None
        updated = None
        if ns:
            last_meta = get_version(storage, name, ns[-1])
            updated = (last_meta or {}).get("timestamp")

        rows.append({
            "name": name,
            "description": header.get("description"),
            "latest_version": latest,
            "aliases": fold["aliases"],
            "versions_count": len(ns),
            "updated": updated,
        })
    return {"models": rows}
