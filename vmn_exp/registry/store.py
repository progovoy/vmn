"""Registry storage: model header and version records.

All records live in the reserved app ``vmn-registry`` in the experiment
storage.  Model headers are stored as records with verstr equal to the model
name; version records use ``<model>.v<N>``.

Storage is duck-typed (any SnapshotStorage-compatible object).
"""
from __future__ import annotations

import datetime

from vmn_exp.registry.names import parse_version_record, valid_model_name, version_record_name

REGISTRY_APP = "vmn-registry"
_DEFAULT_STATUS = "active"


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def list_models(storage) -> list[str]:
    """Return the names of all registered models (no version records)."""
    try:
        verstrs = storage.list_verstrs(REGISTRY_APP)
    except Exception:
        return []
    return [v for v in verstrs if parse_version_record(v) is None]


def list_versions(storage, model_name: str) -> list[dict]:
    """Return metadata dicts for every version of *model_name*, sorted by N."""
    try:
        verstrs = storage.list_verstrs(REGISTRY_APP)
    except Exception:
        return []
    version_records = [
        v for v in verstrs
        if parse_version_record(v) is not None
        and parse_version_record(v)[0] == model_name
    ]
    results = []
    for verstr in version_records:
        meta = storage.load_metadata(REGISTRY_APP, verstr)
        if meta:
            results.append(meta)
    results.sort(key=lambda m: m.get("version", 0))
    return results


def ensure_model(storage, model_name: str, description: str | None = None) -> bool:
    """Create the model header record if absent.  Returns True when created."""
    meta = {
        "model": model_name,
        "description": description,
        "created": _now_iso(),
    }
    return storage.create_exclusive(REGISTRY_APP, model_name, meta, {})


def register_version(storage, model_name: str, version_meta: dict) -> int:
    """Atomically claim the next version number and write the record.

    Returns the version number assigned.  *version_meta* must contain at
    minimum a ``run`` dict.  Raises ``ValueError`` on a name collision (should
    not happen in practice; callers can retry).
    """
    ensure_model(storage, model_name)

    # Find the current max version number.
    try:
        all_verstrs = storage.list_verstrs(REGISTRY_APP)
    except Exception:
        all_verstrs = []

    existing_ns = []
    for v in all_verstrs:
        parsed = parse_version_record(v)
        if parsed and parsed[0] == model_name:
            existing_ns.append(parsed[1])

    n = (max(existing_ns) if existing_ns else 0) + 1
    verstr = version_record_name(model_name, n)

    meta = {
        "model": model_name,
        "version": n,
        "status": version_meta.get("status", _DEFAULT_STATUS),
        "run": version_meta.get("run", {}),
        "artifact_path": version_meta.get("artifact_path"),
        "artifact_uri": version_meta.get("artifact_uri"),
        "description": version_meta.get("description"),
        "created": _now_iso(),
    }
    claimed = storage.create_exclusive(REGISTRY_APP, verstr, meta, {})
    if not claimed:
        raise ValueError(f"Version record {verstr!r} already exists")
    return n
