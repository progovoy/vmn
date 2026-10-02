"""The one lookup of a run's code record (metadata + patches), shared by
``vmn goto -v <dev-version>`` and ``vmn-exp restore``.

Search order: the app's experiment store as configured (local first, the
remote store only on a local miss), then the snapshots store (safety
snapshots and ``vmn snapshot create`` records, whose code objects live in the
experiment store). A record without a code snapshot (e.g. an MLflow import) is
refused.
"""
from vmn_exp.cli.provenance import refuse_no_code
from vmn_exp.core.code_store import CODE_MISSING, resolve_code
from vmn_exp.core.storage_resolve import _get_experiment_storage, store_uri
from vmn_exp.core.writer import STORAGE_ENV
from vmn_exp.snapshot import _get_storage
from version_stamp.api import VMN_LOGGER


def load_code_record(vcs, params, verstr, app_name=None, exp_storage=None):
    """``(metadata, patches)`` of *verstr*, or None after logging why not.

    *params* are experiment storage params (``experiment_storage_params``);
    *exp_storage* is the already-open experiment storage, if the caller has one.
    """
    app_name = app_name or vcs.name
    if exp_storage is None:
        exp_storage = _open_experiment_storage(vcs, params)
    metadata, patches = _try_load(exp_storage, app_name, verstr, "experiment")
    if metadata is None:
        metadata, patches = _load_snapshot(
            _open_snapshot_storage(vcs, params), app_name, verstr, exp_storage
        )
    if metadata is None:
        VMN_LOGGER.error(
            f"Dev version {verstr} not found (searched: {_searched(params)})"
        )
        return None
    if refuse_no_code(metadata, action="restore") is not None:
        return None
    return metadata, patches


def _open_experiment_storage(vcs, params):
    try:
        return _get_experiment_storage(vcs, params)
    except Exception:
        VMN_LOGGER.debug("Could not open the experiment store", exc_info=True)
        return None


def _open_snapshot_storage(vcs, params):
    try:
        return _get_storage(vcs, params)
    except Exception:
        VMN_LOGGER.debug("Could not open the snapshot store", exc_info=True)
        return None


def _try_load(storage, app_name, verstr, kind):
    if storage is None:
        return None, None
    try:
        return storage.load(app_name, verstr)
    except Exception:
        VMN_LOGGER.debug(f"{kind} load of {verstr} failed", exc_info=True)
        return None, None


def _load_snapshot(storage, app_name, verstr, exp_storage):
    """A snapshot record; ``vmn snapshot create`` keeps its code object with
    the experiments' (the shared code store), not beside the record."""
    metadata, patches = _try_load(storage, app_name, verstr, "snapshot")
    if not (metadata or {}).get(CODE_MISSING) or exp_storage is None:
        return metadata, patches
    record, own_patches = storage.load_record(app_name, verstr)
    return resolve_code(exp_storage, app_name, record, own_patches)


def _searched(params):
    storage_params = {key: params.get(key) for key in STORAGE_ENV}
    places = ["local experiments"]
    uri = store_uri(storage_params)
    if uri:
        places.append(f"remote experiment store {uri}")
    places.append("local snapshots")
    if uri:
        places.append(f"remote snapshot store {uri}")
    return ", ".join(places)
