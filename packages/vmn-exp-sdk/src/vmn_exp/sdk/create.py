#!/usr/bin/env python3
"""Creating the experiment records behind ``start_run()``, ``create_run()``
and ``create_runs()``.

Two modes, as with the CLI: a git checkout (cold-start if needed, snapshot the
tree) and a container built from ``vmn-exp export`` (no git; record against
the exported code's identity). Either is first a :data:`RecordSource` — what
every run recorded from it shares — then a claim per run under its lock. The
checkout mode lives in :mod:`vmn_exp.gitmode.checkout`, which only the full
vmn-exp package ships.
"""
import collections
import contextlib
import os

import yaml
from vmn_exp._base import ensure_logger
from vmn_exp.core import create_batch
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.env import (
    capture_env_safe,
    should_capture,
)
from vmn_exp.core.from_snapshot import exported_features, snapshot_record
from vmn_exp.core.refs import resolve_parent
from vmn_exp.core.storage_resolve import _get_experiment_storage
from vmn_exp.core.writer import create_run as record_run
from vmn_exp.core.writer import get_repo_lock, merge_env_into_params
from vmn_exp.sdk import _resolve_app_name, context
from vmn_exp.sdk.context import current_run

SNAPSHOT_METADATA_ENV = "VMN_SNAPSHOT_METADATA"
GIT_MODE_MISSING = (
    "This run needs a git checkout, and git mode is not installed: "
    "`pip install vmn-exp` for it, or record git-free by setting "
    f"{SNAPSHOT_METADATA_ENV} and VMN_EXPERIMENT_DIR/VMN_EXPERIMENT_BUCKET."
)

# What every run created from one checkout capture or export shares: *template*
# is the record's metadata minus its identity, *lock* a context-manager factory
# held while claiming, *exp_conf* the checkout's ``experiment:`` conf.
RecordSource = collections.namedtuple(
    "RecordSource",
    "app_name storage code_verstr template parent env features lock exp_conf")


def gitmode():
    """``vmn_exp.gitmode.checkout``, which only the full vmn-exp ships."""
    try:
        from vmn_exp.gitmode import checkout
    except ImportError as exc:
        raise RuntimeError(GIT_MODE_MISSING) from exc
    return checkout


def create_run(
    app_name=None, *, name=None, params=None, note=None, parent=None, storage=None,
    capture_env=None, run_id=None, tags=None,
):
    """Register a run without starting it; returns its verstr.

    *run_id* names it exactly — ``<code_verstr>.<suffix>`` of the code being
    recorded (ValueError otherwise) — with one exclusive create and no listing
    of the code version's runs; RunExistsError when the name is taken. *tags*
    are set in its create entry.

    The run reads ``created`` (a fleet's *waiting*) until a process takes it
    with ``start_run(run_id=<verstr>)``. Its parent is *parent*, else the
    calling context's open run, else ``VMN_EXPERIMENT_ID`` — so a launcher
    inside its outer run registers every pod up front and the outer run's
    totals are right before any pod starts. Many at once: :func:`create_runs`.
    """
    run = dict(name=name, params=params, note=note, run_id=run_id, tags=tags)
    return create_runs(app_name, [run], parent=parent, storage=storage,
                       capture_env=capture_env, workers=1)[0]


def create_runs(
    app_name=None, runs=(), *, parent=None, storage=None, capture_env=False,
    workers=16, exist_ok=False,
):
    """Register a batch of waiting runs; their verstrs, in the order of *runs*.

    Each item of *runs* is a dict of ``name``, ``params``, ``tags``, ``note``
    and ``run_id``, all optional (see :func:`create_run`). The batch shares one
    parent (picked as :func:`create_run` picks it), one checkout capture or
    export read, one environment capture (off unless *capture_env*) and one
    lock; the code version's runs are listed at most once (twice when another
    host took a name meanwhile), and the runs are claimed *workers* at a time. A bad item refuses the batch before anything
    is created. A taken ``run_id`` raises RunExistsError once the others are
    created — unless *exist_ok* and that run has the same parent and name, so
    a restarted launcher can register its batch again.
    """
    ensure_logger()
    specs = create_batch.run_specs(runs)
    if not specs:
        return []
    source = record_source(app_name, parent, True, storage, capture_env)
    with source.lock():
        return create_batch.create_runs(
            source.storage, source.app_name, source.code_verstr, source.template,
            specs, parent=source.parent, env=source.env, features=source.features,
            workers=workers, exist_ok=exist_ok,
        )


def create_record(
    app_name, note, params, parent, nested, storage, name=None,
    capture_env=None, python_exe=None,
):
    """Create a new run's record; ``(app_name, storage, verstr, exp_conf)``.

    *exp_conf* is the checkout's ``experiment:`` conf (``{}`` without one).
    """
    _reject_reentry_without_nesting(nested)
    # Same shape as the CLI's `-f file` params, so latest_metrics and
    # `exp diff` pick them up unchanged.
    create_data = {"params": dict(params)} if params else None
    source = record_source(app_name, parent, nested, storage, capture_env, python_exe)
    with source.lock():
        verstr = record_run(
            source.storage, source.app_name, source.code_verstr,
            dict(source.template, note=note), {}, note=note, create_data=create_data,
            parent=source.parent, name=name, env=source.env, features=source.features,
        )
    return source.app_name, source.storage, verstr, source.exp_conf


def record_source(app_name, parent, nested, storage, capture_env, python_exe=None):
    """The :data:`RecordSource` new runs record from: the export
    ``VMN_SNAPSHOT_METADATA`` names, else the checkout."""
    meta_path = os.environ.get(SNAPSHOT_METADATA_ENV)
    if meta_path:
        return snapshot_source(app_name, meta_path, parent, nested, storage, capture_env)
    return gitmode().checkout_source(
        app_name, parent, nested, storage, capture_env=capture_env, python_exe=python_exe)


def creation_failed(app_name, err):
    """The error a source that could not be built raises (*err*: its code)."""
    return RuntimeError(
        f"Failed to create an experiment for '{app_name}' (error {err}). "
        f"Run 'vmn-exp create {app_name}' to see what the CLI reports."
    )


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
    params = {}
    merge_env_into_params(params)
    try:
        return _get_experiment_storage(None, params)
    except ValueError:
        raise ValueError(
            "No experiment store for a run without a git checkout: "
            "set VMN_EXPERIMENT_DIR and/or VMN_EXPERIMENT_STORE (or pass storage=)."
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

    While this process has runs open, ``VMN_EXPERIMENT_ID`` is their own export,
    never a launcher: the value the process was started with is used instead,
    read atomically so a sibling closing mid-pick cannot leak through.
    """
    if parent:
        resolved, err = resolve_parent(storage, app_name, parent)
        if err:
            raise ValueError(f"Unknown parent experiment: {parent}")
        return resolved

    enclosing = current_run() if nested else None
    if enclosing is not None:
        return enclosing.id

    ref = context.launcher_experiment_id()
    return resolve_parent(storage, app_name, env_ref=ref)[0]


def snapshot_source(app_name, meta_path, parent, nested, storage, capture_env=None):
    """Container mode: the :data:`RecordSource` of an exported snapshot, no
    git needed."""
    app_name = _resolve_app_name(app_name, lambda: snapshot_app_names(meta_path))
    if storage is None:
        storage = snapshot_mode_storage()
    record = snapshot_record(meta_path, app_name)
    if record is None:
        raise creation_failed(app_name, 1)
    app_name, code_verstr, template = record
    # Env and the export's features are read OUTSIDE the lock.
    env = _maybe_capture_env(None, capture_env)
    features = exported_features(meta_path)
    parent = pick_parent(storage, app_name, parent, nested)
    return RecordSource(app_name, storage, code_verstr, template, parent, env,
                        features, _shared_dir_lock, {})


def _shared_dir_lock():
    """A shared VMN_EXPERIMENT_DIR is the only thing concurrent git-less workers
    have in common: serialize verstr allocation on it, like a checkout's lock."""
    lock_root = os.environ.get("VMN_EXPERIMENT_DIR")
    if not lock_root:
        return contextlib.nullcontext()
    os.makedirs(os.path.join(lock_root, ".vmn"), exist_ok=True)
    return get_repo_lock(lock_root)


def _maybe_capture_env(vcs, capture_env_param, python_exe=None):
    """Return the captured env dict, or None when opted out or capture fails."""
    if not should_capture(capture_env_param, experiment_conf(vcs)):
        return None
    return capture_env_safe(python_exe)
