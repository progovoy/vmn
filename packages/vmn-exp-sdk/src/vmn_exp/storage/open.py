"""Build the storage a command or run reads and writes.

A remote store (``s3://``, ``gs://``, ``az://``, a plugin scheme) is fronted
by the local root when there is one (local-first, synced) and, without one, is
used directly — through a private log buffer for writers. A ``file://`` store
*is* the local root.
"""
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.registry import open_store


def open_storage(store=None, vmn_root_path=None, subdir="snapshots", buffer_logs=False):
    """The storage for *store* (a URI, or None) over *vmn_root_path*.

    ``buffer_logs``: without a local root, still buffer logs locally (a
    private temp dir) and ship them as segments — for writers; a pure-remote
    reader has no use for it.
    """
    remote = open_store(store, subdir=subdir) if store else None
    if remote is not None and not remote.is_remote():
        return CachedSnapshotStorage(remote, None)
    if vmn_root_path:
        return CachedSnapshotStorage(
            LocalSnapshotStorage(vmn_root_path, subdir=subdir), remote
        )
    if remote is None:
        raise ValueError(
            "No experiment storage: pass --store/--dir (or set "
            "VMN_EXPERIMENT_STORE / VMN_EXPERIMENT_DIR)"
        )
    if buffer_logs:
        from vmn_exp.storage.buffered import BufferedRemoteStorage

        return BufferedRemoteStorage(remote, subdir=subdir)
    return remote

