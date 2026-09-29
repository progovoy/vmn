"""Registry helpers shared by dataset registration (SDK and CLI) and usage.

* ``producer_output`` — the ``{path, digest, size}`` a run logged for a path.
* ``reference_fields`` — ``uri``/``digest``/``size``/``files`` of a reference
  dataset: a local path is made absolute and hashed, a remote URI keeps the
  caller's digest (or none).
* ``version_with_digest`` — the newest live version carrying a digest (dedupe).
"""
from __future__ import annotations

import os

from vmn_exp.core.fold import fold_log, fold_outputs_dict
from vmn_exp.core.log import load_log
from vmn_exp.registry.digest import local_digest
from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries
from vmn_exp.registry.store import get_version, list_versions


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
