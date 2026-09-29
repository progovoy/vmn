"""Registry helpers shared by dataset registration (SDK and CLI) and usage.

* ``producer_output`` — the ``{path, digest, size}`` a run logged for a path.
* ``reference_fields`` — ``uri``/``digest``/``size``/``files`` of a reference
  dataset: a local path is made absolute and hashed, a remote URI keeps the
  caller's digest (or none).
* ``copied_fields`` — the fields of a dataset stored as run artifact *path*.
* ``version_with_digest`` — the newest live version carrying a digest (dedupe).
* ``register_dataset_version`` — ensure a dataset header, then reuse the
  version with the same digest (``dedupe``) or claim a new one.
"""
from __future__ import annotations

import os

from vmn_exp.core.fold import fold_log, fold_outputs_dict
from vmn_exp.core.log import load_log
from vmn_exp.registry.digest import local_digest
from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries
from vmn_exp.registry.store import ensure_model, get_version, list_versions, register_version


def producer_output(storage, app, verstr, path) -> dict | None:
    """``{path, digest, size}`` of output *path* of run *verstr*, else None."""
    return fold_outputs_dict(fold_log(load_log(storage, app, verstr))).get(path)


def reference_fields(uri: str, digest: str | None = None) -> dict:
    """Version fields of a dataset referenced at *uri* (no bytes copied)."""
    if "://" in uri:
        return {"uri": uri, "digest": digest}
    if not os.path.exists(uri):
        raise FileNotFoundError(f"Dataset path not found: {uri}")
    fields = local_digest(uri)
    if digest is not None:
        fields["digest"] = digest
    return {"uri": os.path.abspath(uri), **fields}


def copied_fields(storage, run_ref: dict, path, digest: str | None = None) -> dict:
    """Version fields of a dataset logged as artifact *path* of *run_ref*:
    the digest (unless given) and size are the ones the run logged."""
    output = {}
    if run_ref.get("app") and path:
        output = producer_output(storage, run_ref["app"], run_ref["verstr"], path) or {}
    return {
        "run_ref": run_ref,
        "artifact_path": path,
        "digest": digest or output.get("digest"),
        "size": output.get("size"),
    }


def version_with_digest(storage, name: str, digest: str) -> int | None:
    """The newest non-deleted version of *name* whose digest is *digest*."""
    status = fold_registry(read_entries(storage, name))["status"]
    for n in reversed(list_versions(storage, name)):
        if status.get(n) == "deleted":
            continue
        meta = get_version(storage, name, n) or {}
        if meta.get("digest") == digest:
            return n
    return None


def register_dataset_version(storage, name, fields, description=None, dedupe=True) -> int:
    """The version number of dataset *name* carrying *fields* (``run_ref``,
    ``artifact_path``, ``uri``, ``digest``, ``size``, ``files``)."""
    ensure_model(storage, name, kind="dataset")
    if dedupe and fields.get("digest"):
        n = version_with_digest(storage, name, fields["digest"])
        if n is not None:
            return n
    return register_version(storage, name, description=description, **fields)
