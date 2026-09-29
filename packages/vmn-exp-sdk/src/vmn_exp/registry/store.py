"""Registry record storage: models and their version claims.

Records live in experiment storage under the reserved pseudo-app ``vmn-registry``.

Model header record:  ``<model>``       — one per model, carries description/actor.
Version record:       ``<model>.v<N>``  — immutable; claimed atomically via
                                          ``create_exclusive``; numbers never reused
                                          (abandoned claims keep their slot).

Public surface
--------------
ensure_model(storage, model, description=None, actor=None)
register_version(storage, model, run_ref, artifact_path=None, description=None, actor=None) -> int
list_versions(storage, model) -> [int]
list_models(storage) -> [str]
get_version(storage, model, n) -> metadata dict | None

Timestamps come from ``vmn_exp.registry.fold.now_iso``; vmn_exp modules may
not import ``version_stamp.*`` except ``version_stamp.api`` (rule 11).
"""
from __future__ import annotations

from vmn_exp.core.record_format import readable, stamped
from vmn_exp.registry.fold import now_iso
from vmn_exp.registry.names import (
    REGISTRY_APP,
    parse_version_record,
    valid_model_name,
    version_record_name,
)

_MAX_REGISTER_RETRIES = 200


def ensure_model(storage, model, description=None, actor=None):
    """Create the model header record if absent.  Idempotent.

    ``create_exclusive`` is atomic: concurrent callers both succeed — the
    second one gets False and does nothing.
    """
    metadata = {"model": model, "type": "model_header", "timestamp": now_iso()}
    if description is not None:
        metadata["description"] = description
    if actor is not None:
        metadata["actor"] = actor
    # Return value ignored: False = record already exists, that is fine.
    storage.create_exclusive(REGISTRY_APP, model, stamped(metadata), {})


def register_version(
    storage,
    model,
    run_ref,
    artifact_path=None,
    description=None,
    actor=None,
) -> int:
    """Atomically claim the next version number for *model* and return it.

    Algorithm
    ---------
    1. List all record names under ``vmn-registry``.
    2. Collect all taken ``N`` values for ``<model>.v<N>`` — includes
       abandoned (partial) claims so their numbers are never reused.
    3. Start at ``max(taken) + 1`` (or 1 when *taken* is empty).
    4. Attempt ``create_exclusive``; on collision re-read the listing and
       jump to the new max+1.  Bounded to ``_MAX_REGISTER_RETRIES``.

    Raises ``RuntimeError`` after too many collisions (should not happen
    unless more than 200 concurrent writers race on the same model).
    """
    all_names = list(storage.list_record_names(REGISTRY_APP))
    n = max(_taken_version_numbers(all_names, model), default=0) + 1

    metadata_base = stamped({"model": model, "run_ref": run_ref, "timestamp": now_iso()})
    if artifact_path is not None:
        metadata_base["artifact_path"] = artifact_path
    if description is not None:
        metadata_base["description"] = description
    if actor is not None:
        metadata_base["actor"] = actor

    attempts = 0
    while attempts < _MAX_REGISTER_RETRIES:
        record_name = version_record_name(model, n)
        if storage.create_exclusive(REGISTRY_APP, record_name, dict(metadata_base, n=n), {}):
            return n
        # Collision: re-read and jump to the new max+1.
        all_names = list(storage.list_record_names(REGISTRY_APP))
        taken = _taken_version_numbers(all_names, model)
        n = max(max(taken, default=0) + 1, n + 1)
        attempts += 1

    raise RuntimeError(
        f"Could not claim a version slot for model {model!r} "
        f"after {_MAX_REGISTER_RETRIES} attempts"
    )


def list_versions(storage, model) -> list:
    """Sorted list of version numbers for *model* that have complete records."""
    all_names = list(storage.list_record_names(REGISTRY_APP))
    return sorted(
        n
        for name, n in _version_names_for_model(all_names, model)
        if storage.exists(REGISTRY_APP, name)
    )


def list_models(storage) -> list:
    """Sorted list of model names that have complete header records."""
    all_names = list(storage.list_record_names(REGISTRY_APP))
    return sorted(
        name
        for name in all_names
        if parse_version_record(name) is None
        and valid_model_name(name)
        and storage.exists(REGISTRY_APP, name)
    )


def get_version(storage, model, n) -> dict | None:
    """Return the metadata dict for version *n* of *model*, or None."""
    record_name = version_record_name(model, n)
    metadata, _ = storage.load(REGISTRY_APP, record_name)
    return readable(metadata, record_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _version_names_for_model(all_names, model):
    """Yield ``(record_name, n)`` for every ``<model>.v<N>`` name in *all_names*."""
    for name in all_names:
        parsed = parse_version_record(name)
        if parsed is not None and parsed[0] == model:
            yield name, parsed[1]


def _taken_version_numbers(all_names, model) -> set:
    """Version numbers (int) in *all_names* for *model*, including abandoned claims."""
    return {n for _, n in _version_names_for_model(all_names, model)}
