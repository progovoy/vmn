"""Registry record storage: models and their version claims.

Records live in the store's ``registry`` area, one scope per model
(``registry/<model>/``):

Model header record:  ``header``  — one per model, carries description/actor.
Version record:       ``v<N>``    — immutable; claimed atomically via
                                    ``create_exclusive``; numbers never reused
                                    (abandoned claims keep their slot).

Public surface
--------------
ensure_model(storage, model, description=None, actor=None, kind="model")
model_kind(storage, model) -> "model" | "dataset" | None
register_version(storage, model, run_ref=None, artifact_path=None, description=None,
                 actor=None, uri=None, digest=None, size=None, files=None) -> int
list_versions(storage, model) -> [int]
list_models(storage, kind=None) -> [str]
get_version(storage, model, n) -> metadata dict | None

Timestamps come from ``vmn_exp.registry.fold.now_iso``; vmn_exp modules may
not import ``version_stamp.*`` except ``version_stamp.api`` (rule 11).
"""
from __future__ import annotations

from vmn_exp.core.record_format import readable, stamped
from vmn_exp.registry.fold import now_iso
from vmn_exp.storage.areas import REGISTRY
from vmn_exp.registry.names import (
    HEADER_RECORD,
    KINDS,
    parse_version_record,
    valid_model_name,
    version_record_name,
)

_MAX_REGISTER_RETRIES = 200


def registry_storage(storage):
    """The ``registry`` area of *storage*'s root (one scope per model)."""
    return storage.in_area(REGISTRY)


def ensure_model(storage, model, description=None, actor=None, kind="model"):
    """Create the model header record if absent.  Idempotent.

    ``create_exclusive`` is atomic: concurrent callers both succeed — the
    second one gets False and does nothing.  *kind* is ``model`` or
    ``dataset``; an existing header of the other kind raises ``ValueError``
    (a header without ``kind`` is a model).
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown registry kind {kind!r}; use one of {KINDS}")
    metadata = {"model": model, "type": "model_header", "kind": kind, "timestamp": now_iso()}
    if description is not None:
        metadata["description"] = description
    if actor is not None:
        metadata["actor"] = actor
    if registry_storage(storage).create_exclusive(model, HEADER_RECORD, stamped(metadata), {}):
        return
    existing = model_kind(storage, model)
    if existing is not None and existing != kind:
        raise ValueError(f"{model!r} is registered as a {existing}, not a {kind}")


def model_kind(storage, model) -> str | None:
    """``model``/``dataset`` of *model*'s header; None when it has none."""
    return header_kind(load_header(storage, model))


def load_header(storage, model):
    """*model*'s header metadata, or None."""
    return registry_storage(storage).load(model, HEADER_RECORD)[0]


def header_kind(header) -> str | None:
    """``model``/``dataset`` of a loaded *header* (no ``kind`` = model)."""
    if not isinstance(header, dict):
        return None
    return header.get("kind") or "model"


def run_of(meta) -> tuple | None:
    """``(app, verstr)`` of the run a version record points at, else None."""
    run_ref = (meta or {}).get("run_ref")
    if isinstance(run_ref, dict) and run_ref.get("app") and run_ref.get("verstr"):
        return run_ref["app"], run_ref["verstr"]
    return None


def register_version(
    storage,
    model,
    run_ref=None,
    artifact_path=None,
    description=None,
    actor=None,
    *,
    uri=None,
    digest=None,
    size=None,
    files=None,
) -> int:
    """Atomically claim the next version number for *model* and return it.

    Algorithm
    ---------
    1. List the record names of the model's scope.
    2. Collect all taken ``N`` values for ``v<N>`` — includes
       abandoned (partial) claims so their numbers are never reused.
    3. Start at ``max(taken) + 1`` (or 1 when *taken* is empty).
    4. Attempt ``create_exclusive``; on collision re-read the listing and
       jump to the new max+1.  Bounded to ``_MAX_REGISTER_RETRIES``.

    *run_ref* is optional: a reference dataset has none, only its
    *uri*/*digest*/*size*/*files*.

    Raises ``RuntimeError`` after too many collisions (should not happen
    unless more than 200 concurrent writers race on the same model).
    """
    reg = registry_storage(storage)
    n = max(_taken_version_numbers(reg, model), default=0) + 1

    metadata_base = stamped(_version_metadata(
        model, run_ref=run_ref, artifact_path=artifact_path,
        description=description, actor=actor,
        uri=uri, digest=digest, size=size, files=files,
    ))

    attempts = 0
    while attempts < _MAX_REGISTER_RETRIES:
        if reg.create_exclusive(model, version_record_name(n), dict(metadata_base, n=n), {}):
            return n
        # Collision: re-read and jump to the new max+1.
        taken = _taken_version_numbers(reg, model)
        n = max(max(taken, default=0) + 1, n + 1)
        attempts += 1

    raise RuntimeError(
        f"Could not claim a version slot for model {model!r} "
        f"after {_MAX_REGISTER_RETRIES} attempts"
    )


def list_versions(storage, model) -> list:
    """Sorted list of version numbers for *model* that have complete records."""
    reg = registry_storage(storage)
    return sorted(
        n for n in _taken_version_numbers(reg, model)
        if reg.exists(model, version_record_name(n))
    )


def list_models(storage, kind=None) -> list:
    """Sorted list of model names that have complete header records, only
    those of *kind* (``model``/``dataset``) when given."""
    reg = registry_storage(storage)
    candidates = [name for name in reg.list_apps() if valid_model_name(name)]
    if kind is None:
        return [name for name in candidates if reg.exists(name, HEADER_RECORD)]
    return [name for name in candidates if model_kind(storage, name) == kind]


def get_version(storage, model, n) -> dict | None:
    """Return the metadata dict for version *n* of *model*, or None."""
    record_name = version_record_name(n)
    metadata, _ = registry_storage(storage).load(model, record_name)
    return readable(metadata, f"{REGISTRY}/{model}/{record_name}", owner=storage)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _version_metadata(model, **fields):
    """A version record's fields, the ``None`` ones left out."""
    metadata = {"model": model, "timestamp": now_iso()}
    metadata.update((k, v) for k, v in fields.items() if v is not None)
    return metadata


def _taken_version_numbers(reg, model) -> set:
    """Version numbers of *model*'s ``v<N>`` records, including abandoned claims."""
    numbers = (parse_version_record(name) for name in reg.list_record_names(model))
    return {n for n in numbers if n is not None}
