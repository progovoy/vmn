"""SDK helpers for datasets in the registry.

Datasets share the model registry's namespace (a header ``kind: dataset``).
Two modes:

* **reference** (default) — ``register_dataset(name, uri)``: no bytes are
  copied. A local file or directory is hashed (a file's sha256, a directory's
  manifest digest); a remote URI keeps the *digest* the caller passes, if any.
* **copied** — log the data as an artifact of a data-prep run, then
  ``register_dataset(name, run=..., artifact_path=...)``: the version points
  at that artifact, so prune protects the run and lineage shows it.

With ``dedupe=True`` (the default) registering a digest the dataset already
has returns that version instead of claiming a new one.

Usage::

    from vmn_exp.sdk import register_dataset, use_dataset

    register_dataset("imagenet", "/data/imagenet", alias="train")
    with start_run("my_app") as run:
        meta = run.use_dataset("imagenet@train")
"""
from __future__ import annotations

from vmn_exp.registry.datasets import copied_fields, reference_fields, register_dataset_version
from vmn_exp.registry.log import set_alias as _log_set_alias
from vmn_exp.registry.view import resolve_ref
from vmn_exp.sdk.models import _resolve_storage, _run_to_ref, check_model_name
from vmn_exp.sdk.usage import resolved_version


def register_dataset(
    name,
    uri=None,
    *,
    run=None,
    app_name=None,
    artifact_path=None,
    digest=None,
    description=None,
    alias=None,
    dedupe=True,
    storage=None,
) -> dict:
    """Register a dataset version and return its metadata dict.

    Pass exactly one of *uri* (reference mode) or *artifact_path* (copied
    mode; *run* / *app_name* as for ``register_model``, default: the current
    run). *digest* overrides the computed one (``sha256:<hex>``).
    """
    check_model_name(name)
    if (uri is None) == (artifact_path is None):
        raise ValueError(
            "Pass exactly one of uri= (reference a dataset) or "
            "artifact_path= (a dataset logged as an artifact of run=)."
        )
    if uri is not None:
        storage = _resolve_storage(storage)
        fields = reference_fields(uri, digest)
    else:
        app, verstr, run_storage = _run_to_ref(run, app_name)
        storage = _resolve_storage(storage or run_storage)
        fields = copied_fields(storage, {"app": app, "verstr": verstr}, artifact_path, digest)

    n = register_dataset_version(storage, name, fields, description=description, dedupe=dedupe)
    if alias:
        _log_set_alias(storage, name, alias, n)
    return resolve_ref(storage, f"{name}@{n}")


def get_dataset_version(ref, *, storage=None) -> dict:
    """Resolve dataset *ref* (``name``, ``name@N``, ``name@alias``) to its
    version metadata. Records no use; ValueError when *ref* is a model."""
    return resolved_version(_resolve_storage(storage), ref, "dataset")

