#!/usr/bin/env python3
"""Creating the experiment record behind ``start_run()``.

Two modes, as with the CLI: a git checkout (cold-start if needed, snapshot the
tree) and a container built from ``vmn snapshot export`` (no git; record against
the exported snapshot's identity).

In a checkout, the repo lock is held only to claim the verstr. The snapshot is
captured before that (see :mod:`version_stamp.exp.capture`) and the cold start
takes the lock on its own, only when there is something to initialize.
"""
import contextlib
import os
from types import SimpleNamespace

import yaml

# Still upward, and deliberately so: the storage factory and the snapshot
# record builders live in version_stamp/cli. Lifting exp/ into its own
# distribution needs these to move into core next.
from version_stamp.cli.experiment import _get_experiment_storage, _resolve_parent
from version_stamp.cli.snapshot import (
    _build_snapshot_metadata,
    _format_dev_verstr,
    _resolve_verstr,
)
from version_stamp.core.experiment_from_snapshot import create_from_snapshot
from version_stamp.core.experiment_writer import (
    allocate_run_verstr,
    append_to_log,
    attach_parent,
    create_log_entry,
    get_repo_lock,
    merge_conf_into_params,
    merge_env_into_params,
)
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import resolve_root_path
from version_stamp.exp import _resolve_app_name, capture, context
from version_stamp.exp.coldstart import tracked_vcs
from version_stamp.exp.context import EXPERIMENT_ID_ENV, current_run

SNAPSHOT_METADATA_ENV = "VMN_SNAPSHOT_METADATA"


def create_record(app_name, note, params, parent, nested, storage, snapshot):
    """Create a new run's record; ``(app_name, storage, verstr)``."""
    # Same shape as the CLI's `-f file` params, so _get_latest_metrics and
    # `exp diff` pick them up unchanged.
    create_data = {"params": dict(params)} if params else None
    meta_path = os.environ.get(SNAPSHOT_METADATA_ENV)
    if meta_path:
        app_name, storage, verstr, err = create_from_snapshot_meta(
            app_name, meta_path, note, create_data, parent, nested, storage
        )
    else:
        app_name, storage, verstr, err = create_in_checkout(
            app_name, note, create_data, parent, nested, storage, snapshot
        )
    if err:
        raise RuntimeError(
            f"Failed to create an experiment for '{app_name}' (error {err}). "
            f"Run 'vmn exp create {app_name}' to see what the CLI reports."
        )
    return app_name, storage, verstr


def stamped_apps():
    from version_stamp.cli.completion import _complete_apps

    return _complete_apps("")


def build_storage(vcs):
    params = {"backend": "local", "prefix": "vmn-experiments"}
    merge_conf_into_params(vcs, params)
    return _get_experiment_storage(vcs, params)


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
        resolved, err = _resolve_parent(
            storage, app_name, SimpleNamespace(parent=parent)
        )
        if err:
            raise ValueError(f"Unknown parent experiment: {parent}")
        return resolved

    enclosing = current_run() if nested else None
    if enclosing is not None:
        return enclosing.id

    ref = os.environ.get(EXPERIMENT_ID_ENV)
    if ref and context.is_foreign_sibling(ref):
        ref = context.launcher_experiment_id()
    return _resolve_env_parent(storage, app_name, ref)


def _resolve_env_parent(storage, app_name, ref):
    """An env-provided parent: resolved against storage, dropped when stale."""
    if not ref:
        return None
    verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
    if err:
        VMN_LOGGER.warning(f"Ignoring stale VMN_EXPERIMENT_ID '{ref}': {err}")
        return None
    return verstr


def create_from_snapshot_meta(
    app_name, meta_path, note, create_data, parent, nested, storage
):
    """Container mode: record against an exported snapshot, no git needed."""
    app_name = _resolve_app_name(app_name, lambda: snapshot_app_names(meta_path))
    if storage is None:
        storage = snapshot_mode_storage()
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
        )
    return app_name, storage, verstr, err


def create_in_checkout(
    app_name, note, create_data, parent, nested, storage, snapshot=True
):
    """The normal mode: cold-start if needed, capture, then claim under the lock."""
    app_name = _resolve_app_name(app_name, stamped_apps)
    root_path = resolve_root_path()
    os.makedirs(os.path.join(root_path, ".vmn"), exist_ok=True)

    vcs, status = tracked_vcs(app_name, root_path)
    captured, err = capture.capture_snapshot(vcs, snapshot=snapshot, status=status)
    if err is not None:
        return app_name, storage, None, err
    if storage is None:
        storage = build_storage(vcs)
    parent = pick_parent(storage, app_name, parent, nested)

    # The claim itself is atomic (create_exclusive); the lock keeps a run from
    # being created while another vmn command holds the repo.
    with get_repo_lock(root_path):
        verstr = _record(vcs, storage, captured, note, create_data, parent)
    return app_name, storage, verstr, None


def _record(vcs, storage, captured, note, create_data, parent):
    """Claim a verstr for *captured* and write the record and its create entry."""
    code_verstr = _format_dev_verstr(
        captured.base_version, captured.commit_hash, captured.diff_hash
    )
    template = _build_snapshot_metadata(
        vcs,
        code_verstr,
        captured.base_version,
        captured.commit_hash,
        captured.dirty_states,
        captured.payload,
        captured.ver_info,
        note=note,
    )
    # The payload may be empty (snapshot=False): identity comes from what was
    # captured, not from what is stored.
    if captured.diff_hash:
        template["diff_hash"] = captured.diff_hash
    if not captured.snapshot:
        template["snapshot"] = False
    template["code_verstr"] = code_verstr

    def make_record(verstr):
        metadata = dict(template, verstr=verstr)
        attach_parent(metadata, parent)
        return metadata, captured.payload

    verstr = allocate_run_verstr(storage, vcs.name, code_verstr, make_record=make_record)
    entry = create_log_entry("create", note=note)
    if create_data:
        entry.update(create_data)
    append_to_log(storage, vcs.name, verstr, entry)
    return verstr
