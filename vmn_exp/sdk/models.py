"""SDK helpers for the vmn model registry.

The registry lives in the same storage root as experiment runs (under the
reserved pseudo-app ``vmn-registry``).  These functions provide a Python API
for registering model versions, managing aliases, and downloading artifacts.

Usage::

    from vmn_exp.sdk import start_run
    from vmn_exp.sdk.models import register_model, download_model

    with start_run("my_app") as run:
        # ... training ...
        run.log_artifact("model.pkl")
        version = run.register_model("my_model", artifact_path="model.pkl")

    path = download_model("my_model@production")
"""
from __future__ import annotations

import os
import shutil

from vmn_exp.registry.log import remove_alias as _log_remove_alias
from vmn_exp.registry.log import set_alias as _log_set_alias
from vmn_exp.registry.names import valid_model_name
from vmn_exp.registry.store import ensure_model
from vmn_exp.registry.store import list_models as _list_models
from vmn_exp.registry.store import register_version
from vmn_exp.registry.view import resolve_ref


def _resolve_storage(storage=None):
    """Resolve experiment storage from env or the current checkout."""
    if storage is not None:
        return storage
    from vmn_exp.core.storage_resolve import resolve_experiment_storage
    return resolve_experiment_storage()


def _run_to_ref(run, app_name):
    """Extract *(app_name, verstr, storage_or_None)* from a run reference.

    *run* may be:
    - a :class:`~vmn_exp.sdk.run.Run` instance
    - a verstr string (requires *app_name* to be provided)
    - ``None`` — the currently active run from :func:`~vmn_exp.sdk.current_run`
    """
    if run is None:
        from vmn_exp.sdk.context import current_run

        run = current_run()
        if run is None:
            raise ValueError(
                "No active run and run= was not provided. "
                "Call register_model inside start_run() or pass run=<run>."
            )

    if isinstance(run, str):
        if not app_name:
            raise ValueError(
                "app_name is required when run= is a verstr string."
            )
        return app_name, run, None

    # Duck-type: a Run instance has .id and .app_name
    resolved_app = app_name or getattr(run, "app_name", None)
    verstr = getattr(run, "id", None)
    run_storage = getattr(run, "_storage", None)
    if not resolved_app or not verstr:
        raise ValueError(
            f"Cannot extract app_name / verstr from run={run!r}. "
            "Pass a Run instance, a verstr string, or leave run=None for the active run."
        )
    return resolved_app, verstr, run_storage


def register_model(
    name,
    run=None,
    app_name=None,
    artifact_path=None,
    description=None,
    alias=None,
    *,
    storage=None,
) -> dict:
    """Register a model version in the registry and return its metadata dict.

    Parameters
    ----------
    name:
        Model name (letters, digits, ``_``, ``.``; no hyphens; no ``.vN`` suffix).
    run:
        The experiment run that produced this model.  Accepts a
        :class:`~vmn_exp.sdk.run.Run` instance, a verstr string, or
        ``None`` (defaults to the active run from :func:`current_run`).
    app_name:
        VMN app name — required when *run* is a verstr string.
    artifact_path:
        Relative artifact path within the run (e.g. ``"model/weights.pkl"``).
    description:
        Human-readable description of this version.
    alias:
        If given, immediately point this alias at the new version.
    storage:
        Explicit storage object; resolved from env / checkout when omitted.

    Returns
    -------
    dict
        The version metadata dict (``n``, ``run_ref``, ``artifact_path``, …).
    """
    if not valid_model_name(name):
        raise ValueError(
            f"Invalid model name {name!r}: use letters, digits, underscore, dot; "
            "no hyphens; must not end with .vN."
        )

    resolved_app, verstr, run_storage = _run_to_ref(run, app_name)
    storage = _resolve_storage(storage or run_storage)

    run_ref = {"app": resolved_app, "verstr": verstr}
    ensure_model(storage, name)
    n = register_version(
        storage,
        name,
        run_ref=run_ref,
        artifact_path=artifact_path,
        description=description,
    )

    if alias:
        _log_set_alias(storage, name, alias, n)

    return get_model_version(f"{name}@{n}", storage=storage)


def set_alias(model, alias, version, expect=None, *, storage=None) -> None:
    """Point *alias* at *version* in *model*'s registry.

    *version* must be an existing version number (int).
    *expect* is the version number the caller expects the alias to currently
    hold, or ``"none"`` if it expects the alias to be absent; a mismatch
    raises :class:`ValueError`.
    """
    storage = _resolve_storage(storage)
    _log_set_alias(storage, model, alias, version, expect=expect)


def remove_alias(model, alias, *, storage=None) -> None:
    """Remove *alias* from *model*'s registry."""
    storage = _resolve_storage(storage)
    _log_remove_alias(storage, model, alias)


def get_model_version(ref, *, storage=None) -> dict:
    """Resolve *ref* to a version metadata dict.

    Supported forms: ``model@alias``, ``model@3``, ``model@latest``, ``model``.
    Raises :class:`KeyError` when the alias is unknown or the version is deleted.
    """
    storage = _resolve_storage(storage)
    return resolve_ref(storage, ref)


def list_models(*, storage=None) -> list:
    """Return a sorted list of model names in the registry."""
    storage = _resolve_storage(storage)
    return _list_models(storage)


def download_model(ref, dst=None, *, storage=None) -> str:
    """Download the artifact referenced by *ref* and return its local path.

    Local storage returns the on-disk path directly; S3 storage downloads the
    artifact to a temporary cache directory first.

    Parameters
    ----------
    ref:
        Model reference — ``model@alias``, ``model@N``, ``model@latest``,
        or bare ``model``.
    dst:
        If given, copy the artifact to this directory (created if absent) and
        return the path of the copied file.
    storage:
        Explicit storage; resolved from env / checkout when omitted.
    """
    storage = _resolve_storage(storage)
    meta = get_model_version(ref, storage=storage)

    run_ref = meta.get("run_ref")
    if not isinstance(run_ref, dict):
        raise ValueError(
            f"Model version for {ref!r} has no run_ref — cannot locate artifact."
        )

    artifact_path = meta.get("artifact_path")
    if not artifact_path:
        raise ValueError(
            f"Model version for {ref!r} has no artifact_path — nothing to download."
        )

    app = run_ref["app"]
    verstr = run_ref["verstr"]

    local = _fetch_artifact(storage, app, verstr, artifact_path)

    if dst is not None:
        os.makedirs(dst, exist_ok=True)
        dst_path = os.path.join(dst, os.path.basename(artifact_path))
        shutil.copy2(local, dst_path)
        return dst_path

    return local


def _fetch_artifact(storage, app, verstr, artifact_path) -> str:
    """Return a local filesystem path for *artifact_path* from *storage*.

    All storage backends implement ``artifact_local_path``: local backends return
    the on-disk path directly; S3 downloads to a temp cache first.
    """
    path = storage.artifact_local_path(app, verstr, artifact_path)
    if path is None:
        raise FileNotFoundError(
            f"Artifact {artifact_path!r} not found in storage "
            f"for app={app!r} verstr={verstr!r}."
        )
    return path
