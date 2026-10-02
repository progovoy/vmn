"""``vmn snapshot delete -v REF``: remove a snapshot record, then its code
object unless another snapshot or an experiment run still references it.

Runs (``stores.runs``, when given) are scanned for ``code:`` references too.

Public: ``snapshot_delete(stores, app_name, verstr) -> int``.
"""
from version_stamp.core.logging import VMN_LOGGER


def _referenced_code_keys(stores, app_name):
    keys = set()
    for store in filter(None, (stores.records, stores.runs)):
        keys.update(m.get("code") for m in store.list_snapshots(app_name))
    keys.discard(None)
    return keys


def _drop_code_if_unused(stores, app_name, key):
    if key and key not in _referenced_code_keys(stores, app_name):
        stores.code.delete(app_name, key)


def snapshot_delete(stores, app_name, verstr):
    metadata = stores.records.load_metadata(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1
    stores.records.delete(app_name, verstr)
    _drop_code_if_unused(stores, app_name, metadata.get("code"))
    VMN_LOGGER.info(f"Deleted snapshot {verstr}")
    return 0
