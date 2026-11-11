"""Read-side access to the model registry for the vmn-exp ui API.

Builds the TypeScript-contract shapes (ModelRow, ModelDetail) from the
lower-level registry API in vmn_exp.registry.
"""
from __future__ import annotations

from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries
from vmn_exp.registry.names import HEADER_RECORD
from vmn_exp.registry.store import (
    artifact_uri_of, get_version, header_kind, list_versions, load_header,
)
from vmn_exp.storage.files import METADATA_FILE
from vmn_exp.storage.s3_base import parallel_map
from vmn_exp.ui.registry_snapshot import read_models


def _actor_str(actor) -> str:
    """Convert an actor dict or plain value to a display string."""
    if isinstance(actor, dict):
        return actor.get("writer") or actor.get("git_user_email") or "unknown"
    return str(actor) if actor else "unknown"


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
        "artifact_uri": artifact_uri_of(storage, meta),
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
    header = load_header(storage, model_name)
    if header is None:
        return None, f"Model '{model_name}' not found"

    ns = list_versions(storage, model_name)
    entries = read_entries(storage, model_name)
    fold = fold_registry(entries)

    # Load each version's raw metadata once, reuse in both version list and audit.
    version_metas = dict(zip(ns, parallel_map(lambda n: get_version(storage, model_name, n), ns)))

    alias_by_version: dict = {}
    for alias, ver_n in fold["aliases"].items():
        alias_by_version.setdefault(ver_n, []).append(alias)

    versions = [_version_detail(storage, version_metas[n], fold, alias_by_version, n) for n in ns]
    audit = _build_audit(fold["audit"], version_metas)

    return {
        "name": model_name,
        "kind": header_kind(header),
        "description": header.get("description"),
        "versions": versions,
        "aliases": fold["aliases"],
        "audit": audit,
    }, None


class _ModelRow:
    """One model's ModelRow (None without a header), read when its *files*
    listing changes: its header, log and latest version concurrently."""

    __slots__ = ("files", "row")

    def __init__(self, storage, name, files):
        self.files = files
        records = {r for r, f in files.items() if METADATA_FILE in f}
        if HEADER_RECORD not in records:
            self.row = None
            return
        ns = list_versions(storage, name, records)
        header, entries, last = parallel_map(lambda read: read(), [
            lambda: load_header(storage, name),
            lambda: read_entries(storage, name),
            lambda: get_version(storage, name, ns[-1]) if ns else None,
        ])
        self.row = None if header is None else {
            "name": name,
            "kind": header_kind(header),
            "description": header.get("description"),
            "latest_version": ns[-1] if ns else None,
            "aliases": fold_registry(entries)["aliases"],
            "versions_count": len(ns),
            "updated": (last or {}).get("timestamp"),
        }


class ModelListing:
    """Every model's ModelRow, as the Models page lists them."""

    def __init__(self, models):
        self._models = models

    @classmethod
    def read(cls, storage, previous=None):
        """*storage*'s listing, reusing *previous*'s unchanged models."""
        return cls(read_models(storage, previous._models if previous is not None else {}, _ModelRow))

    def response(self, kind=None) -> dict:
        """``{"models": [ModelRow ...]}``, name-ordered, only *kind*
        (``model``/``dataset``) entries when given."""
        rows = (self._models[name].row for name in sorted(self._models))
        return {"models": [row for row in rows if row and kind in (None, row["kind"])]}


def list_models_response(storage, kind=None) -> dict:
    """Return ``{"models": [ModelRow ...]}`` for the list endpoint, only
    *kind* (``model``/``dataset``) entries when given."""
    return ModelListing.read(storage).response(kind)
