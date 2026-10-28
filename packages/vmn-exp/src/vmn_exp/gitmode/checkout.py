"""Creating runs in a git checkout: cold-start if needed, capture the tree,
then claim each verstr under the repo lock.

The repo lock is held only to claim the verstr. The snapshot is captured before
that (see :mod:`vmn_exp.gitmode.capture`) and the cold start takes the lock on
its own, only when there is something to initialize.
"""
import os

from version_stamp.api import get_repo_lock, resolve_root_path
from vmn_exp.core.storage_resolve import _get_experiment_storage
from vmn_exp.core.writer import create_run, merge_conf_into_params
from vmn_exp.gitmode import capture
from vmn_exp.gitmode.coldstart import build_vcs, tracked_vcs
from vmn_exp.gitmode.features import capture_features
from vmn_exp.sdk import _resolve_app_name
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.sdk.create import (
    RecordSource,
    _maybe_capture_env,
    creation_failed,
    pick_parent,
)
from vmn_exp.snapshot import _build_snapshot_metadata


def stamped_apps():
    from version_stamp.api import _complete_apps

    return _complete_apps("")


def build_storage(vcs):
    params = {}
    merge_conf_into_params(vcs, params)
    return _get_experiment_storage(vcs, params)


def checkout_source(app_name, parent, nested, storage, capture_env=None, python_exe=None):
    """The normal mode's :data:`RecordSource`: cold-start if needed, capture;
    its lock is the repo lock, held only to claim."""
    app_name = _resolve_app_name(app_name, stamped_apps)
    root_path = resolve_root_path()
    os.makedirs(os.path.join(root_path, ".vmn"), exist_ok=True)

    vcs, status = tracked_vcs(app_name, root_path)
    captured, err = capture.capture_snapshot(vcs, status=status)
    if err is not None:
        raise creation_failed(app_name, err)
    if storage is None:
        storage = build_storage(vcs)
    parent = pick_parent(storage, app_name, parent, nested)

    # Capture env and the run's features OUTSIDE the repo lock (both are
    # read-only and may block on subprocess probing), and store the code there
    # too: it is keyed by content, so it needs no lock.
    env = _maybe_capture_env(vcs, capture_env, python_exe=python_exe)
    code = capture.ensure_code(storage, vcs, captured)
    features = capture_features(vcs, captured)
    # The claim itself is atomic (create_exclusive); the lock keeps a run from
    # being created while another vmn command holds the repo.
    return RecordSource(
        app_name, storage, captured.code_verstr, record_template(vcs, captured, code),
        parent, env, features, lambda: get_repo_lock(root_path), experiment_conf(vcs),
    )


def record_template(vcs, captured, code, note=None):
    """A run of *captured*'s metadata, minus the identity a claim stamps on it."""
    return _build_snapshot_metadata(
        vcs,
        captured.code_verstr,
        captured.base_version,
        captured.commit_hash,
        captured.dirty_states,
        captured.identity,
        captured.ver_info,
        note=note,
        code=code,
        diff_hash=captured.diff_hash,
    )


def record_run(vcs, storage, captured, code, note, create_data, parent, name=None,
               env=None, features=None):
    """Claim a verstr for *captured* and write the record and its create entry.

    *code* is :func:`capture.ensure_code`'s ``(key, summary)``: the record
    references the stored code object instead of carrying the patches. The
    run's *features* entry (:func:`capture_features`'s, None without one)
    follows the create entry.
    """
    template = record_template(vcs, captured, code, note=note)
    return create_run(
        storage,
        vcs.name,
        captured.code_verstr,
        template,
        {},
        note=note,
        create_data=create_data,
        parent=parent,
        name=name,
        env=env,
        features=features,
    )
