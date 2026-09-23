#!/usr/bin/env python3
"""Local-first snapshot storage with an optional remote (S3), and the factory.

All writes land on local disk; the remote provides durability and sharing
between hosts. Immutable files fetched from the remote are cached locally;
volatile ones (run state, logs) never are — a cached copy is stale the moment
the owning host writes again.
"""
from version_stamp.cli.snapshot_storage import SnapshotStorage
from version_stamp.cli.snapshot_storage_files import (
    flatten_logs,
    is_volatile_file,
    log_object_name,
    log_writer_and_seq,
)
from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
from version_stamp.cli.snapshot_storage_s3 import S3SnapshotStorage
from version_stamp.core.logging import VMN_LOGGER


class CachedSnapshotStorage(SnapshotStorage):
    """Local-first storage with optional S3 sync. All ops hit local disk;
    S3 provides durability and distribution."""

    def __init__(self, local_storage, remote_storage=None):
        self._local = local_storage
        self._remote = remote_storage
        # (app, verstr, writer) -> (bytes already on the remote, next segment)
        self._synced = {}

    def save(self, app_name, verstr, metadata, patches):
        self._local.save(app_name, verstr, metadata, patches)
        if self._remote:
            try:
                self._remote.save(app_name, verstr, metadata, patches)
            except Exception:
                VMN_LOGGER.warning("Failed to sync snapshot to remote storage")
                VMN_LOGGER.debug("Remote save failed", exc_info=True)
                raise

    def create_exclusive(self, app_name, verstr, metadata, patches):
        if not self._local.create_exclusive(app_name, verstr, metadata, patches):
            return False
        if not self._remote:
            return True
        try:
            claimed = self._remote.create_exclusive(app_name, verstr, metadata, patches)
        except Exception:
            self._local.delete(app_name, verstr)
            raise
        if not claimed:
            # Another host holds this name on the shared remote.
            self._local.delete(app_name, verstr)
        return claimed

    def load(self, app_name, verstr):
        meta, patches = self._local.load(app_name, verstr)
        if meta is not None:
            return meta, patches
        if self._remote:
            meta, patches = self._remote.load(app_name, verstr)
            if meta is not None:
                self._local.save(app_name, verstr, meta, patches)
            return meta, patches
        return None, None

    def exists(self, app_name, verstr):
        if self._local.exists(app_name, verstr):
            return True
        if self._remote:
            return self._remote.exists(app_name, verstr)
        return False

    def _remote_or(self, default, method, *args):
        if not self._remote:
            return default
        try:
            return getattr(self._remote, method)(*args)
        except Exception:
            VMN_LOGGER.debug(f"Remote {method} failed", exc_info=True)
            return default

    def list_verstrs(self, app_name):
        names = list(self._local.list_verstrs(app_name))
        seen = set(names)
        for name in self._remote_or([], "list_verstrs", app_name):
            if name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def list_snapshots(self, app_name):
        local_snaps = self._local.list_snapshots(app_name)
        seen = {m["verstr"] for m in local_snaps}
        all_snaps = list(local_snaps)
        for m in self._remote_or([], "list_snapshots", app_name):
            if m["verstr"] not in seen:
                all_snaps.append(m)
                seen.add(m["verstr"])
        all_snaps.sort(key=lambda m: m.get("timestamp", ""))
        return all_snaps

    def list_files(self, app_name):
        files = {}
        for verstr, remote_files in self._remote_or({}, "list_files", app_name).items():
            files[verstr] = dict(remote_files)
        for verstr, local_files in self._local.list_files(app_name).items():
            files.setdefault(verstr, {}).update(local_files)
        return files

    def direct_files(self):
        # With a remote, a record's log is the per-writer merge of two copies.
        return self._local if self._remote is None else None

    def index_cache_path(self, app_name):
        return self._local.index_cache_path(app_name)

    def cache_identity(self):
        remote = self._remote.cache_identity() if self._remote else None
        return ("cached", self._local.cache_identity(), remote)

    def update_note(self, app_name, verstr, note):
        ok = self._local.update_note(app_name, verstr, note)
        if self._remote:
            try:
                self._remote.update_note(app_name, verstr, note)
            except Exception:
                VMN_LOGGER.debug("Failed to update note on remote", exc_info=True)
                raise
        return ok

    def delete(self, app_name, verstr):
        self._local.delete(app_name, verstr)
        if self._remote:
            try:
                self._remote.delete(app_name, verstr)
            except Exception:
                VMN_LOGGER.debug("Failed to delete from remote", exc_info=True)
                raise

    def load_file(self, app_name, verstr, filename):
        data = self._local.load_file(app_name, verstr, filename)
        if data is not None:
            return data
        if self._remote:
            data = self._remote.load_file(app_name, verstr, filename)
            if data is not None and not is_volatile_file(filename):
                self._local.save_file(app_name, verstr, filename, data)
            return data
        return None

    def _ensure_local_record(self, app_name, verstr):
        """Whether *verstr* may be written into.

        A record that exists nowhere (pruned, never created) is not written:
        that would resurrect it as an invisible zombie. One another host
        created is pulled in first, so local appends have a home.
        """
        if self._local.exists(app_name, verstr):
            return True
        if not (self._remote and self._remote.exists(app_name, verstr)):
            return False
        try:
            self.load(app_name, verstr)
        except Exception:
            VMN_LOGGER.debug("Could not fetch the remote record", exc_info=True)
        return True

    def save_file(self, app_name, verstr, filename, data):
        if not self._ensure_local_record(app_name, verstr):
            VMN_LOGGER.debug(f"Not writing {filename}: {verstr} does not exist")
            return False
        self._local.save_file(app_name, verstr, filename, data)
        if self._remote:
            try:
                self._remote.save_file(app_name, verstr, filename, data)
            except Exception:
                VMN_LOGGER.debug("Failed to save file to remote", exc_info=True)
                raise
        return True

    def save_artifact_file(self, app_name, verstr, src_path):
        if not self._ensure_local_record(app_name, verstr):
            return False
        self._local.save_artifact_file(app_name, verstr, src_path)
        if self._remote:
            try:
                self._remote.save_artifact_file(app_name, verstr, src_path)
            except Exception:
                VMN_LOGGER.debug("Failed to save artifact to remote", exc_info=True)
                raise
        return True

    def list_artifact_files(self, app_name, verstr):
        return self._local.list_artifact_files(app_name, verstr)

    def list_artifacts(self, app_name, verstr):
        found = self._local.list_artifacts(app_name, verstr)
        return found or self._remote_or([], "list_artifacts", app_name, verstr)

    def artifact_local_path(self, app_name, verstr, name):
        path = self._local.artifact_local_path(app_name, verstr, name)
        return path or self._remote_or(
            None, "artifact_local_path", app_name, verstr, name
        )

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        # Local only: sync_log_to_remote ships the new bytes periodically.
        if not self._ensure_local_record(app_name, verstr):
            return False
        return self._local.append_log_entry(app_name, verstr, writer_id, entry)

    def load_logs_by_writer(self, app_name, verstr):
        logs = dict(self._local.load_logs_by_writer(app_name, verstr))
        remote_logs = self._remote_or({}, "load_logs_by_writer", app_name, verstr)
        for writer, entries in remote_logs.items():
            # A writer's log only ever grows, so the longer copy is the newer.
            if len(entries) > len(logs.get(writer, [])):
                logs[writer] = entries
        return logs

    def load_merged_log(self, app_name, verstr):
        local_logs = self._local.load_logs_by_writer(app_name, verstr)
        if not any(local_logs.values()):
            if self._remote:
                return self._remote.load_merged_log(app_name, verstr)
            return []
        return flatten_logs(self.load_logs_by_writer(app_name, verstr))

    def _remote_log_state(self, app_name, verstr, writer_id):
        objects = list(self._remote.log_objects(app_name, verstr, writer_id))
        offset = sum(size for _, size in objects)
        seqs = [log_writer_and_seq(name)[1] for name, _ in objects]
        return offset, (max(seqs) + 1 if seqs else 0)

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        """Ship the writer's complete lines appended since the last sync."""
        if not self._remote:
            return
        base = log_object_name(writer_id)
        data = self._local.load_file(app_name, verstr, base)
        end = data.rfind(b"\n") + 1 if data else 0
        if not end:
            return
        key = (app_name, verstr, writer_id)
        if key not in self._synced:
            self._synced[key] = self._remote_log_state(app_name, verstr, writer_id)
        offset, seq = self._synced[key]
        if offset == end:
            return
        if offset > end:
            # The remote holds more than this host ever wrote: start over.
            self._remote.save_file(app_name, verstr, base, data[:end])
            self._remote.delete_log_segments(app_name, verstr, writer_id)
            self._synced[key] = (end, 1)
            return
        name = log_object_name(writer_id, seq)
        self._remote.save_file(app_name, verstr, name, data[offset:end])
        self._synced[key] = (end, seq + 1)


def get_snapshot_storage(
    backend,
    vmn_root_path=None,
    bucket=None,
    prefix="vmn-snapshots",
    endpoint_url=None,
    subdir="snapshots",
):
    local = None
    remote = None

    if vmn_root_path:
        local = LocalSnapshotStorage(vmn_root_path, subdir=subdir)

    if bucket:
        remote = S3SnapshotStorage(bucket, prefix=prefix, endpoint_url=endpoint_url)

    if backend == "local":
        if not local:
            raise ValueError("vmn_root_path is required for local backend")
        return CachedSnapshotStorage(local, remote)
    elif backend == "s3":
        if not remote:
            raise ValueError("--bucket is required for s3 backend")
        if local:
            return CachedSnapshotStorage(local, remote)
        return remote
    else:
        raise ValueError(f"Unknown backend: {backend}")
