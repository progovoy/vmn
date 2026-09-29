"""Recording that a run used a registered model or dataset version.

A use writes two things:

* an ordinary ``input`` entry on the run, named ``<name>@<N>`` (so two
  versions of one model both survive the latest-wins input fold). A version
  backed by a run artifact gets the ``vmn://`` URI ``run.use_artifact`` would
  record, with the producer output's digest, so lineage links the consumer to
  its producer run; a reference dataset gets ``vmn-registry://<name>@<N>``.
* a ``use`` entry in the registry's ``<name>-uses`` record — best-effort: a
  failed registry write is warned about, never raised.

Refs are always pinned to the resolved number, never an alias. Resolving a
version (``get_model_version``) records nothing; only ``use_model``,
``use_dataset`` and ``download_model(record=True)`` inside a run do.
"""
from __future__ import annotations

import logging
import threading
import weakref

from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.registry.datasets import producer_output
from vmn_exp.registry.log import record_use
from vmn_exp.registry.names import parse_ref, registry_uri
from vmn_exp.registry.store import model_kind
from vmn_exp.registry.view import resolve_ref
from vmn_exp.sdk import context
from vmn_exp.sdk.models import _resolve_storage

_LOGGER = logging.getLogger("vmn_exp.sdk")
_USED = weakref.WeakKeyDictionary()  # run -> {(name, n)} it already recorded
_USED_LOCK = threading.Lock()


def use_model(ref, *, run=None, storage=None) -> dict:
    """Resolve model *ref* and record that *run* (default: the current run)
    used it. Returns the version metadata; without a run it only resolves."""
    return _use(ref, "model", run, storage)


def use_dataset(ref, *, run=None, storage=None) -> dict:
    """:func:`use_model` for a dataset *ref*."""
    return _use(ref, "dataset", run, storage)


def resolved_version(storage, ref, kind) -> dict:
    """*ref*'s version metadata; ValueError when it names the other kind."""
    name = parse_ref(ref)[0]
    actual = model_kind(storage, name)
    if actual is not None and actual != kind:
        helper = "use_model" if actual == "model" else "use_dataset"
        raise ValueError(f"{name!r} is a {actual}, not a {kind} — use {helper}()")
    return resolve_ref(storage, ref)


def record_current_use(storage, meta) -> None:
    """Record *meta*'s version as used by the current run, if one is open."""
    run = context.current_run()
    if run is not None:
        record_version_use(run, storage, meta, model_kind(storage, meta["model"]) or "model")


def record_version_use(run, storage, meta, kind) -> None:
    """Log *meta*'s version as an input of *run*, then note the use in the
    registry. A run records each version once."""
    key = (meta["model"], meta["n"])
    with _USED_LOCK:
        if key in _USED.get(run, ()):
            return
    run.log_input(**_version_input(storage, meta, kind))
    with _USED_LOCK:
        _USED.setdefault(run, set()).add(key)
    try:
        record_use(storage, meta["model"], meta["n"], run.app_name, run.id)
    except Exception as exc:  # noqa: BLE001 — the run must not fail on it
        _LOGGER.warning(f"vmn: could not record the use of {key[0]}@{key[1]} "
                        f"by run {run.id} in the registry: {exc}")


def _use(ref, kind, run, storage):
    run = run if run is not None else context.current_run()
    storage = _resolve_storage(storage or getattr(run, "_storage", None))
    meta = resolved_version(storage, ref, kind)
    if run is not None:
        record_version_use(run, storage, meta, kind)
    return meta


def _version_input(storage, meta, kind) -> dict:
    """``log_input`` keywords naming *meta*'s version."""
    name, n = meta["model"], meta["n"]
    uri, digest = registry_uri(name, n), meta.get("digest")
    run_ref, path = meta.get("run_ref"), meta.get("artifact_path")
    if isinstance(run_ref, dict) and run_ref.get("app") and run_ref.get("verstr") and path:
        app, verstr = run_ref["app"], run_ref["verstr"]
        uri = artifact_ref_uri(app, verstr, path)
        output = producer_output(storage, app, verstr, path)
        digest = (output or {}).get("digest") or digest
    return {"uri": uri, "name": f"{name}@{n}", "digest": digest, "kind": kind}
