#!/usr/bin/env python3
"""Creating the experiment record behind ``start_run()``.

Two modes, as with the CLI: a git checkout (cold-start if needed, snapshot the
tree) and a container built from ``vmn snapshot export`` (no git; record against
the exported snapshot's identity). The checkout mode lives in
:mod:`vmn_exp.gitmode.checkout`, which only the full vmn-exp package ships.
"""
import contextlib
import os

import yaml

from vmn_exp.core.env import (
    CAPTURE_ENV_ENV,
    capture_env_safe,
    should_capture,
)
from vmn_exp.core.from_snapshot import create_from_snapshot
from vmn_exp.core.refs import resolve_parent
from vmn_exp.core.storage_resolve import _get_experiment_storage
from vmn_exp.core.writer import get_repo_lock, merge_env_into_params
from vmn_exp.sdk import _resolve_app_name, context
from vmn_exp.sdk.context import EXPERIMENT_ID_ENV, current_run

SNAPSHOT_METADATA_ENV = "VMN_SNAPSHOT_METADATA"
GIT_MODE_MISSING = (
    "This run needs a git checkout, and git mode is not installed: "
    "`pip install vmn-exp` for it, or record git-free by setting "
    f"{SNAPSHOT_METADATA_ENV} and VMN_EXPERIMENT_DIR/VMN_EXPERIMENT_BUCKET."
)


def gitmode():
    """``vmn_exp.gitmode.checkout``, which only the full vmn-exp ships."""
    try:
        from vmn_exp.gitmode import checkout
    except ImportError as exc:
        raise RuntimeError(GIT_MODE_MISSING) from exc
    return checkout


def create_record(
    app_name, note, params, parent, nested, storage, snapshot, name=None,
    capture_env=None, python_exe=None,
):
    """Create a new run's record; ``(app_name, storage, verstr)``."""
    _reject_reentry_without_nesting(nested)
    # Same shape as the CLI's `-f file` params, so latest_metrics and
    # `exp diff` pick them up unchanged.
    create_data = {"params": dict(params)} if params else None
    meta_path = os.environ.get(SNAPSHOT_METADATA_ENV)
    if meta_path:
        app_name, storage, verstr, err = create_from_snapshot_meta(
            app_name, meta_path, note, create_data, parent, nested, storage, name,
            capture_env=capture_env,
        )
    else:
        app_name, storage, verstr, err = gitmode().create_in_checkout(
            app_name, note, create_data, parent, nested, storage, snapshot, name,
            capture_env=capture_env, python_exe=python_exe,
        )
    if err:
        raise RuntimeError(
            f"Failed to create an experiment for '{app_name}' (error {err}). "
            f"Run 'vmn-exp create {app_name}' to see what the CLI reports."
        )
    return app_name, storage, verstr


def _reject_reentry_without_nesting(nested):
    """Guard against silently chaining a new run under a stale open one.

    Re-running a notebook cell that never called ``run.finish()`` calls
    ``start_run()`` again on the same thread/context while the previous run is
    still open. Without this, ``pick_parent``'s env-var fallback would treat
    that still-open run's self-export as an enclosing launcher and quietly
    parent the new run to it — chaining runs nobody asked to nest, and leaking
    the old run's heartbeat thread forever.

    ``context.context_run()`` is thread/context-bound only (no process-wide
    fallback), so a different thread opening its own run — legitimate
    concurrent usage — is never affected. Pass ``nested=True`` to nest under
    the open run on purpose, mirroring mlflow's "run already active" error.
    """
    if nested:
        return
    active = context.context_run()
    if active is not None:
        raise RuntimeError(
            f"Run '{active.id}' is already active on this thread. Call its "
            ".finish() before starting another, or pass nested=True to open "
            "a nested run under it."
        )


def snapshot_mode_storage():
    """Where a git-less run records, as the CLI does: ``VMN_EXPERIMENT_DIR``
    and/or the ``VMN_EXPERIMENT_BUCKET`` it syncs to."""
    params = {"backend": "local", "prefix": "vmn-experiments"}
    merge_env_into_params(params)
    try:
        return _get_experiment_storage(None, params)
    except ValueError:
        raise ValueError(
            "No experiment store for a run without a git checkout: "
            "set VMN_EXPERIMENT_DIR and/or VMN_EXPERIMENT_BUCKET (or pass storage=)."
        )


def snapshot_app_names(meta_path):
    """The app an exported snapshot's metadata names, as resolver candidates."""
    if os.path.isdir(meta_path):
        meta_path = os.path.join(meta_path, "vmn_metadata.yml")
    try:
        with open(meta_path) as f:
            meta = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return []
    app = meta.get("app_name") if isinstance(meta, dict) else None
    return [app] if app else []


def pick_parent(storage, app_name, parent, nested):
    """Resolve the parent experiment, following the CLI's validation policy.

    Precedence: an explicit ``parent`` (a bad one is a hard error), then the
    calling context's open run when ``nested``, then ``VMN_EXPERIMENT_ID`` (a
    stale one is warned about and dropped — the outer run may have been pruned,
    which is no reason to fail this one).

    ``VMN_EXPERIMENT_ID`` naming a run another thread of this process has open is
    a sibling's export, not a launcher: it is skipped in favour of the value the
    process was started with.
    """
    if parent:
        resolved, err = resolve_parent(storage, app_name, parent)
        if err:
            raise ValueError(f"Unknown parent experiment: {parent}")
        return resolved

    enclosing = current_run() if nested else None
    if enclosing is not None:
        return enclosing.id

    ref = os.environ.get(EXPERIMENT_ID_ENV)
    if ref and context.is_foreign_sibling(ref):
        ref = context.launcher_experiment_id()
    return resolve_parent(storage, app_name, env_ref=ref)[0]


def create_from_snapshot_meta(
    app_name, meta_path, note, create_data, parent, nested, storage, name=None,
    capture_env=None,
):
    """Container mode: record against an exported snapshot, no git needed."""
    app_name = _resolve_app_name(app_name, lambda: snapshot_app_names(meta_path))
    if storage is None:
        storage = snapshot_mode_storage()

    # Capture env OUTSIDE the lock.
    env = _maybe_capture_env(None, capture_env)

    # A shared VMN_EXPERIMENT_DIR is the only thing concurrent git-less workers
    # have in common: serialize verstr allocation on it, like a checkout's lock.
    lock_root = os.environ.get("VMN_EXPERIMENT_DIR")
    if lock_root:
        os.makedirs(os.path.join(lock_root, ".vmn"), exist_ok=True)
    with get_repo_lock(lock_root) if lock_root else contextlib.nullcontext():
        verstr, err = create_from_snapshot(
            storage,
            app_name,
            meta_path,
            note=note,
            extra_create_data=create_data,
            parent=pick_parent(storage, app_name, parent, nested),
            name=name,
            env=env,
        )
    return app_name, storage, verstr, err


def _maybe_capture_env(vcs, capture_env_param, python_exe=None):
    """Return the captured env dict, or None when opted out or capture fails."""
    exp_conf = getattr(vcs, "experiment", None) or {}
    if not should_capture(capture_env_param, exp_conf):
        return None
    return capture_env_safe(python_exe)
