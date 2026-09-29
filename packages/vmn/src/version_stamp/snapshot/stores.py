"""Which stores a snapshot command reads and writes.

``SnapshotStores(records, code, where)``: *records* holds snapshot records,
*code* the code objects they reference, *where* names the store for messages
(``"local"`` or a store URI).

``open_snapshot_stores(vcs, params) -> SnapshotStores``: unless
``params["local"]``, the opener registered through
``plugin_api.register_snapshot_store_opener`` (vmn-exp) is asked first —
``opener(vcs, params) -> SnapshotStores | None`` (None: nothing configured).
Otherwise the local stores; ``params["store"]`` without an opener raises
:class:`SnapshotStoreError`.

``local_snapshot_stores(vmn_root_path) -> SnapshotStores``: records in
``.vmn/<app>/snapshots/``, code in the experiment subdir
(``.vmn/vmn-code/<app~>/experiments/``), where experiment runs keep theirs.
"""
from dataclasses import dataclass

from version_stamp.cli import plugin_api
from version_stamp.snapshot.local_store import LocalRecordStore

REMOTE_NEEDS_EXP = "remote snapshot stores need vmn-exp: pip install vmn-exp"


class SnapshotStoreError(RuntimeError):
    pass


@dataclass
class SnapshotStores:
    records: object
    code: object
    where: str


def local_snapshot_stores(vmn_root_path):
    code = LocalRecordStore(vmn_root_path, "experiments")
    records = LocalRecordStore(vmn_root_path, "snapshots", code_store=code)
    return SnapshotStores(records=records, code=code, where="local")


def _opened_by_plugin(vcs, params):
    opener = plugin_api.snapshot_store_opener()
    if opener is None:
        if params.get("store"):
            raise SnapshotStoreError(REMOTE_NEEDS_EXP)
        return None
    return opener(vcs, params)


def open_snapshot_stores(vcs, params):
    stores = None if params.get("local") else _opened_by_plugin(vcs, params)
    return stores or local_snapshot_stores(vcs.vmn_root_path)
