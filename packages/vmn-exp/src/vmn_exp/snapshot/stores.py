"""The configured stores of ``vmn snapshot`` (registered as vmn's snapshot
store opener, see ``version_stamp.snapshot.stores``).

The store comes from ``--store`` > ``VMN_EXPERIMENT_STORE`` > the bucket
env/shorthand > conf ``experiment.storage.uri``; ``VMN_EXP_OFFLINE`` or no
store at all leaves vmn on its local stores. Snapshot records live in the
store's ``snapshots`` subdir (where restore safety snapshots are), code objects
in its experiment subdir, so snapshots and runs share them.

Public: ``open_configured_snapshot_stores(vcs, params) -> ConfiguredStores | None``.
"""
from dataclasses import dataclass

from vmn_exp.core.code_store import resolve_code
from vmn_exp.core.storage_resolve import (
    _get_experiment_storage,
    drop_remote_if_offline,
    store_uri,
)
from vmn_exp.core.writer import STORAGE_ENV, merge_conf_into_params
from vmn_exp.storage.open import open_storage


@dataclass
class ConfiguredStores:
    """What ``version_stamp.snapshot.stores.SnapshotStores`` carries."""

    records: object
    code: object
    where: str


class RecordsWithCode:
    """Snapshot records whose ``load`` resolves ``code:`` in *code_store*."""

    def __init__(self, records, code_store):
        self._records = records
        self.code_store = code_store

    def __getattr__(self, name):
        return getattr(self._records, name)

    def load(self, app_name, verstr):
        metadata, patches = self._records.load_record(app_name, verstr)
        return resolve_code(self.code_store, app_name, metadata, patches)


def _storage_params(vcs, params):
    storage_params = {key: params.get(key) for key in STORAGE_ENV}
    merge_conf_into_params(vcs, storage_params)
    return drop_remote_if_offline(storage_params, vcs.vmn_root_path)


def open_configured_snapshot_stores(vcs, params):
    storage_params = _storage_params(vcs, params)
    where = store_uri(storage_params)
    if where is None:
        return None
    code = _get_experiment_storage(vcs, storage_params)
    records = open_storage(
        store_uri(storage_params, default_prefix="vmn-snapshots"),
        vcs.vmn_root_path, subdir="snapshots",
    )
    return ConfiguredStores(RecordsWithCode(records, code), code, where)
