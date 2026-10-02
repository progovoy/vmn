"""The configured stores of ``vmn snapshot`` (registered as vmn's snapshot
store opener, see ``version_stamp.snapshot.stores``).

The store comes from ``--store`` > ``VMN_EXPERIMENT_STORE`` > the bucket
env/shorthand > conf ``experiment.storage.uri``; ``VMN_EXP_OFFLINE`` or no
store at all leaves vmn on its local stores. Snapshot records live in the
store's ``snapshots`` area (where restore safety snapshots are), code objects
in its ``code`` area, so snapshots and runs share them.

Public: ``open_configured_snapshot_stores(vcs, params) -> ConfiguredStores | None``.
"""
from dataclasses import dataclass

from vmn_exp.core.code_store import code_storage, resolve_code
from vmn_exp.core.storage_resolve import (
    _get_experiment_storage,
    drop_remote_if_offline,
    store_uri,
)
from vmn_exp.core.writer import STORAGE_ENV, merge_conf_into_params
from vmn_exp.storage.areas import SNAPSHOTS, local_store_root
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.store_marker import require_store


@dataclass
class ConfiguredStores:
    """What ``version_stamp.snapshot.stores.SnapshotStores`` carries."""

    records: object
    code: object
    where: str
    runs: object


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
    writer = not params.get("read_only")
    runs = _get_experiment_storage(vcs, storage_params, writer=writer)
    records = open_storage(where, local_store_root(vcs.vmn_root_path), area=SNAPSHOTS,
                           writer=writer)
    if not writer:
        require_store(records, where)
    return ConfiguredStores(RecordsWithCode(records, runs), code_storage(runs), where, runs)
