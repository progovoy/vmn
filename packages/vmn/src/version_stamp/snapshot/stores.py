"""Which stores a snapshot command reads and writes.

``SnapshotStores(records, code, where, runs=None)``: *records* holds snapshot
records, *code* the code objects they reference, *where* names the store for
messages (``"local"`` or a store URI), *runs* the experiment runs that may
reference code too (None: they live in *code*'s store).

``open_snapshot_stores(vcs, params) -> SnapshotStores``: unless
``params["local"]``, the opener registered through
``plugin_api.register_snapshot_store_opener`` (vmn-exp) is asked first —
``opener(vcs, params) -> SnapshotStores | None`` (None: nothing configured).
Otherwise the local stores; ``params["store"]`` without an opener raises
:class:`SnapshotStoreError`.

``local_snapshot_stores(vmn_root_path) -> SnapshotStores``: records in
``.vmn/store/snapshots/<app-key>/``, code in ``.vmn/store/code/<app-key>/``
(shared with the runs of ``.vmn/store/experiments/<app-key>/``).
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
    runs: object = None


def local_snapshot_stores(vmn_root_path):
    code = LocalRecordStore(vmn_root_path, "code")
    records = LocalRecordStore(vmn_root_path, "snapshots", code_store=code)
    runs = LocalRecordStore(vmn_root_path, "experiments", code_store=code)
    return SnapshotStores(records=records, code=code, where="local", runs=runs)


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
