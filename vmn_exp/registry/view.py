"""Registry read side: model state and ref resolution.

Combines version records (from store) and the alias/status log (from log) into
the shapes the UI and CLI expect.
"""
from __future__ import annotations

from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import LOG_FILE, _read_log
from vmn_exp.registry.names import parse_ref, parse_version_record
from vmn_exp.registry.store import REGISTRY_APP, list_models, list_versions


def model_state(storage, model_name: str) -> dict | None:
    """Return the full model detail dict, or None when the model doesn't exist.

    Shape matches the TypeScript ``ModelDetail`` interface::

        {
            "name": str,
            "description": str | None,
            "versions": [ModelVersion ...],
            "aliases": {alias: version_number},
            "audit": [AuditEntry ...],
        }
    """
    header = storage.load_metadata(REGISTRY_APP, model_name)
    if header is None:
        return None

    version_metas = list_versions(storage, model_name)
    entries = _read_log(storage, model_name)
    folded = fold_registry(entries)

    aliases = folded.get("aliases", {})  # {alias: version_number}
    status_overrides = folded.get("status", {})  # {version_number: status}

    # Build reverse map: version → [alias, ...]
    aliases_for: dict[int, list[str]] = {}
    for alias, ver in aliases.items():
        aliases_for.setdefault(ver, []).append(alias)

    versions = []
    for meta in version_metas:
        n = meta.get("version")
        status = status_overrides.get(n, meta.get("status", "active"))
        versions.append({
            "version": n,
            "status": status,
            "run": meta.get("run", {}),
            "artifact_path": meta.get("artifact_path"),
            "artifact_uri": meta.get("artifact_uri"),
            "aliases": sorted(aliases_for.get(n, [])),
            "created": meta.get("created"),
            "description": meta.get("description"),
        })

    audit = _build_audit(entries, version_metas)

    return {
        "name": model_name,
        "description": header.get("description"),
        "versions": versions,
        "aliases": aliases,
        "audit": audit,
    }


def list_model_rows(storage) -> list[dict]:
    """Return a list of ``ModelRow`` dicts for every registered model.

    Shape matches the TypeScript ``ModelRow`` interface.
    """
    model_names = list_models(storage)
    rows = []
    for name in sorted(model_names):
        header = storage.load_metadata(REGISTRY_APP, name)
        if header is None:
            continue
        version_metas = list_versions(storage, name)
        entries = _read_log(storage, name)
        folded = fold_registry(entries)
        aliases = folded.get("aliases", {})

        latest = max((m.get("version", 0) for m in version_metas), default=None)
        if not version_metas:
            latest = None

        # Most recent timestamp from versions or header
        updated = max(
            [m.get("created") for m in version_metas if m.get("created")]
            + [header.get("created")]
            or [None],
            default=None,
        )
        if updated is None and version_metas:
            updated = version_metas[-1].get("created")

        rows.append({
            "name": name,
            "description": header.get("description"),
            "latest_version": latest,
            "aliases": aliases,
            "versions_count": len(version_metas),
            "updated": updated,
        })
    return rows


def resolve_ref(storage, ref: str) -> dict | None:
    """Resolve a model reference (``model``, ``model@alias``, ``model@N``,
    ``model@latest``) to a ``ModelVersion`` dict, or None when not found.
    """
    model_name, kind, value = parse_ref(ref)
    state = model_state(storage, model_name)
    if state is None:
        return None
    versions = state["versions"]
    if not versions:
        return None

    if kind == "version":
        return next((v for v in versions if v["version"] == value), None)
    if kind == "alias":
        ver_n = state["aliases"].get(value)
        if ver_n is None:
            return None
        return next((v for v in versions if v["version"] == ver_n), None)
    # kind == "latest"
    return versions[-1] if versions else None


def registered_runs(storage) -> set[tuple[str, str]]:
    """Return the set of ``(app_name, verstr)`` pairs for all registered versions."""
    try:
        all_verstrs = storage.list_verstrs(REGISTRY_APP)
    except Exception:
        return set()
    result = set()
    for verstr in all_verstrs:
        parsed = parse_version_record(verstr)
        if parsed is None:
            continue
        meta = storage.load_metadata(REGISTRY_APP, verstr)
        if meta and isinstance(meta.get("run"), dict):
            run = meta["run"]
            app = run.get("app")
            vs = run.get("verstr")
            if app and vs:
                result.add((app, vs))
    return result


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------

def _build_audit(log_entries: list[dict], version_metas: list[dict]) -> list[dict]:
    """Build audit trail from version records and log entries.

    Shape matches the TypeScript ``AuditEntry`` interface.
    """
    audit = []

    # Add a "register" entry for each version in creation order
    for meta in version_metas:
        actor_info = meta.get("actor") or {}
        actor_str = (
            actor_info.get("writer") if isinstance(actor_info, dict)
            else str(actor_info)
        ) or "unknown"
        audit.append({
            "ts": meta.get("created") or "",
            "actor": actor_str,
            "type": "register",
            "alias": None,
            "version": meta.get("version"),
            "status": None,
        })

    # Add log entries (alias moves and status changes)
    for entry in log_entries:
        etype = entry.get("type", "")
        actor_info = entry.get("actor") or {}
        actor_str = (
            actor_info.get("writer") if isinstance(actor_info, dict)
            else str(actor_info)
        ) or entry.get("writer") or "unknown"
        audit.append({
            "ts": entry.get("ts") or "",
            "actor": actor_str,
            "type": etype,
            "alias": entry.get("alias"),
            "version": entry.get("version"),
            "status": entry.get("status"),
        })

    # Sort by timestamp
    audit.sort(key=lambda e: e.get("ts") or "")
    return audit
