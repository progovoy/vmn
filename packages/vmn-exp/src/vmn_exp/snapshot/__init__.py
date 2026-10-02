#!/usr/bin/env python3
"""Dev-version capture and restore: the building block behind experiments
and ``vmn goto -v <dev-version>``."""
# The dev-version helpers live in version_stamp.devversion; the names below
# stay importable from here for experiment code.
from vmn_exp.core.resolve_ref import _resolve_verstr  # noqa: F401
from vmn_exp.core.storage_resolve import store_uri
from vmn_exp.core.writer import STORAGE_ENV, merge_conf_into_params
from vmn_exp.storage.areas import SNAPSHOTS, local_store_root
from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: F401
from vmn_exp.storage.open import open_storage  # noqa: F401
from version_stamp.api import (  # noqa: F401
    VMN_LOGGER,
    # dev-version capture
    _compute_diff_hash,
    _compute_verstr,
    _format_dev_verstr,
    _unique_snapshot_verstr,
    gather_create_data,
    # dev-version materialize
    _diff_real_tree,
    _diff_with_external_tool,
    _materialize_workdir,
    _strip_git_dirs,
    get_git_difftool,
    render_tree_diff,
    # dev-version untracked
    _untracked_caps,
)
from version_stamp.api import build_record_metadata as _build_snapshot_metadata
from version_stamp.api import open_snapshot_stores, restore_record
from version_stamp.api import patch_summary as _patch_summary  # noqa: F401

# The command that brings back the work a dev-version restore saved.
GOTO_HINT = "vmn goto -v {verstr} {app}"


def _get_storage(vcs, params):
    """The checkout's snapshots, fronting the app's experiment store (flags,
    then ``VMN_EXPERIMENT_*``, then conf ``experiment.storage``)."""
    storage_params = {key: params.get(key) for key in STORAGE_ENV}
    merge_conf_into_params(vcs, storage_params)
    return open_storage(store_uri(storage_params), local_store_root(vcs.vmn_root_path),
                        area=SNAPSHOTS)


def _restore_with_safety_net(vcs, params, metadata, patches):
    """Restore a dev version through ``vmn snapshot``'s restore: the work it
    replaces is saved as a snapshot first (refused while untracked files over
    the size caps would be lost, unless ``params["force"]``). *metadata* must
    come from ``load_code_record``, which refuses a record without usable code
    before anything is touched."""
    stores = open_snapshot_stores(vcs, params)
    return restore_record(vcs, params, stores, (metadata, patches), GOTO_HINT)