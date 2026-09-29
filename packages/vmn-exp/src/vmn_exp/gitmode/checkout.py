"""Creating a run in a git checkout: cold-start if needed, capture the tree,
then claim the verstr under the repo lock.

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
from vmn_exp.sdk import _resolve_app_name
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.sdk.create import _maybe_capture_env, pick_parent
from vmn_exp.snapshot import _build_snapshot_metadata, _format_dev_verstr


def stamped_apps():
    from version_stamp.api import _complete_apps

    return _complete_apps("")


def build_storage(vcs):
    params = {}
    merge_conf_into_params(vcs, params)
    return _get_experiment_storage(vcs, params)


def create_in_checkout(
    app_name, note, create_data, parent, nested, storage, snapshot=True, name=None,
    capture_env=None, python_exe=None,
):
    """The normal mode: cold-start if needed, capture, then claim under the lock."""
    app_name = _resolve_app_name(app_name, stamped_apps)
    root_path = resolve_root_path()
    os.makedirs(os.path.join(root_path, ".vmn"), exist_ok=True)

    vcs, status = tracked_vcs(app_name, root_path)
    captured, err = capture.capture_snapshot(vcs, snapshot=snapshot, status=status)
    if err is not None:
        return app_name, storage, None, err, {}
    if storage is None:
        storage = build_storage(vcs)
    parent = pick_parent(storage, app_name, parent, nested)

    # Capture env OUTSIDE the repo lock (it is read-only and may block on
    # subprocess probing).
    env = _maybe_capture_env(vcs, capture_env, python_exe=python_exe)

    # The claim itself is atomic (create_exclusive); the lock keeps a run from
    # being created while another vmn command holds the repo.
    with get_repo_lock(root_path):
        verstr = _record(vcs, storage, captured, note, create_data, parent, name,
                         env=env)
    return app_name, storage, verstr, None, experiment_conf(vcs)


def _record(vcs, storage, captured, note, create_data, parent, name=None, env=None):
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
    return create_run(
        storage,
        vcs.name,
        code_verstr,
        template,
        captured.payload,
        note=note,
        create_data=create_data,
        parent=parent,
        name=name,
        env=env,
    )
