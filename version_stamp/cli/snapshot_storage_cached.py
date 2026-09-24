#!/usr/bin/env python3
"""Local-first snapshot storage with an optional remote (S3), and the factory.

All writes land on local disk; the remote provides durability and sharing
between hosts. Immutable files fetched from the remote are cached locally;
volatile ones (run state, logs) never are — a cached copy is stale the moment
the owning host writes again. Logs: :mod:`snapshot_storage_cached_logs`.

Listings are all-or-nothing: a remote that fails to list raises, because a
merge missing its remote half reads as "those records are gone" — and the
index would forget them, prune would miscount what it keeps.
"""
import os

from version_stamp.cli.snapshot_storage import SnapshotStorage
from version_stamp.cli.snapshot_storage_cached_logs import CachedLogs
from version_stamp.cli.snapshot_storage_files import (
    METADATA_FILE,
    is_volatile_file,
)
from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
from version_stamp.cli.snapshot_storage_s3 import S3SnapshotStorage
from version_stamp.core.logging import VMN_LOGGER


def _local_record_sigs(local, app_name):
    """``{name: (st_mtime_ns, st_ino)}`` of the local record dirs: a record
    dir changes whenever a file in it is created, replaced or removed."""
    names = {}
    for verstr in local.list_verstrs(app_name):
        try:
            st = os.stat(local._snapshot_dir(app_name, verstr))
        except (OSError, ValueError):
            continue
        names[verstr] = (st.st_mtime_ns, st.st_ino)
    return names


class CachedSnapshotStorage(CachedLogs, SnapshotStorage):
    """Local-first storage with optional S3 sync. All ops hit local disk;
    S3 provides durability and distribution."""

    def __init__(self, local_storage, remote_storage=None):
        self._local = local_storage
        self._remote = remote_storage
        self._init_logs()

    def _local_patches(self, patches):
        """What of a record's body the local copy keeps: all of it, unless
        the local copy is only a log buffer."""
        return patches if self._local_is_replica else {}

    def save(self, app_name, verstr, metadata, patches):
        self._local.save(app_name, verstr, metadata, self._local_patches(patches))
        if self._remote:
            try:
                self._remote.save(app_name, verstr, metadata, patches)
            except Exception:
                VMN_LOGGER.warning("Failed to sync snapshot to remote storage")
                VMN_LOGGER.debug("Remote save failed", exc_info=True)
                raise

    def create_exclusive(self, app_name, verstr, metadata, patches):
        local_patches = self._local_patches(patches)
        if not self._local.create_exclusive(app_name, verstr, metadata, local_patches):
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
        """Best effort, for reads where a missing remote answer loses nothing."""
        if not self._remote:
            return default
        try:
            return getattr(self._remote, method)(*args)
        except Exception:
            VMN_LOGGER.debug(f"Remote {method} failed", exc_info=True)
            return default

    def _remote_listing(self, default, method, *args, **kwargs):
        """A remote listing; raises when the remote fails (see the module doc)."""
        if not self._remote:
            return default
        return getattr(self._remote, method)(*args, **kwargs)

    def list_verstrs(self, app_name):
        names = list(self._local.list_verstrs(app_name))
        seen = set(names)
        for name in self._remote_listing([], "list_verstrs", app_name):
            if name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def list_record_names(self, app_name):
        """``{name: local dir signature, or None for a remote-only record}``."""
        names = dict.fromkeys(self._remote_record_names(app_name))
        names.update(_local_record_sigs(self._local, app_name))
        return names

    def _remote_record_names(self, app_name):
        if not self._remote:
            return []
        if hasattr(self._remote, "list_record_names"):
            return self._remote.list_record_names(app_name)
        return self._remote.list_verstrs(app_name)

    def list_snapshots(self, app_name):
        local_snaps = self._local.list_snapshots(app_name)
        seen = {m["verstr"] for m in local_snaps}
        all_snaps = list(local_snaps)
        for m in self._remote_listing([], "list_snapshots", app_name):
            if m["verstr"] not in seen:
                all_snaps.append(m)
                seen.add(m["verstr"])
        all_snaps.sort(key=lambda m: m.get("timestamp", ""))
        return all_snaps

    def list_files(self, app_name, keys=None):
        """``{verstr: {filename: signature}}`` — every record's, or *keys*'."""
        by_keys = {} if keys is None else {"keys": keys}
        remote = self._remote_listing({}, "list_files", app_name, **by_keys)
        local = self._local_files(app_name, keys)
        return {
            verstr: self._merge_record_files(
                app_name, verstr, remote.get(verstr, {}), local.get(verstr, {})
            )
            for verstr in [*remote, *(v for v in local if v not in remote)]
        }

    def _local_files(self, app_name, keys):
        if not self._local_is_replica:
            return {}
        if keys is None:
            return self._local.list_files(app_name)
        files = {}
        for key in keys:
            try:
                found = self._local.record_files(app_name, key)
            except ValueError:
                continue
            if METADATA_FILE in found:
                files[key] = found
        return files

    def direct_files(self):
        # Per-file reads route each writer's log to the copy the listing picked.
        return self._local if self._remote is None else self

    def record_files(self, app_name, verstr):
        """One record's file signatures, or None when reads merge a remote too."""
        return None if self._remote else self._local.record_files(app_name, verstr)

    def is_remote(self):
        return self._remote is not None

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


def get_snapshot_storage(
    backend,
    vmn_root_path=None,
    bucket=None,
    prefix="vmn-snapshots",
    endpoint_url=None,
    subdir="snapshots",
    buffer_logs=False,
):
    """The storage for *backend*. ``buffer_logs``: without a local dir, still
    buffer logs locally (a private temp dir) and ship them as segments — for
    writers; a pure-S3 reader has no use for it."""
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
        if buffer_logs:
            from version_stamp.cli.snapshot_storage_buffered import (
                BufferedRemoteStorage,
            )

            return BufferedRemoteStorage(remote, subdir=subdir)
        return remote
    else:
        raise ValueError(f"Unknown backend: {backend}")
