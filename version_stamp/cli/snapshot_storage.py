#!/usr/bin/env python3
"""The abstract snapshot/experiment storage surface.

A record is a directory (or key prefix) ``<base>/<verstr>/`` holding
``metadata.yml``, the patches, the per-writer JSONL logs, ``run_state.yml`` and
``artifacts/``. ``metadata.yml`` is written last and is what makes a record
exist: a claimed but unfinished record, or what a deleted one left behind, is
invisible. Backends: :mod:`snapshot_storage_local`, :mod:`snapshot_storage_s3`,
and the local-first :mod:`snapshot_storage_cached`.

The defaults here keep duck-typed or older backends working; the real
backends override them with cheaper, atomic versions.
"""
import os
from abc import ABC, abstractmethod

import yaml

from version_stamp.cli.snapshot_storage_files import (
    LEGACY_LOG_FILE,
    METADATA_FILE,
    valid_artifact_name,
)
from version_stamp.core.utils import parse_record_metadata, yaml_safe_load


class SnapshotStorage(ABC):
    @abstractmethod
    def save(self, app_name, verstr, metadata, patches):
        ...

    @abstractmethod
    def load(self, app_name, verstr):
        ...

    @abstractmethod
    def list_snapshots(self, app_name):
        ...

    def list_verstrs(self, app_name):
        """Names only. Backends override this to avoid parsing any metadata."""
        return [m["verstr"] for m in self.list_snapshots(app_name)]

    def load_metadata(self, app_name, verstr):
        """A record's metadata alone — no patches or tarball — or None."""
        return parse_record_metadata(self.load_file(app_name, verstr, METADATA_FILE))

    def exists(self, app_name, verstr):
        """Check if a snapshot exists without loading its full content."""
        metadata, _ = self.load(app_name, verstr)
        return metadata is not None

    def create_exclusive(self, app_name, verstr, metadata, patches):
        """Save only if *verstr* is free. Backends override this atomically."""
        if self.exists(app_name, verstr):
            return False
        self.save(app_name, verstr, metadata, patches)
        return True

    def list_files(self, app_name):
        """``{verstr: {filename: (size, mtime[, etag])}}`` for cheap staleness
        checks; S3 adds the ETag, since LastModified only has 1s resolution."""
        return {}

    # -- experiment index hooks ----------------------------------------------

    def direct_files(self):
        """The backend whose files *are* the records' files, or None.

        The experiment index reads such a backend incrementally (the new bytes
        of a grown log). A backend whose reads merge several sources returns
        None, and the index re-reads a changed record through it instead.
        """
        return None

    def read_file_from(self, app_name, verstr, filename, offset):
        """*filename*'s bytes from *offset* on, or None when it is missing."""
        data = self.load_file(app_name, verstr, filename)
        return None if data is None else data[offset:]

    def index_cache_path(self, app_name):
        """Where a persistent experiment index for *app_name* may live, or None."""
        return None

    def cache_identity(self):
        """A hashable name for this backend's data, for process-wide caches."""
        return None

    @abstractmethod
    def update_note(self, app_name, verstr, note):
        ...

    @abstractmethod
    def delete(self, app_name, verstr):
        ...

    @abstractmethod
    def load_file(self, app_name, verstr, filename):
        """Load an auxiliary file from a snapshot directory. Returns bytes or None."""
        ...

    @abstractmethod
    def save_file(self, app_name, verstr, filename, data):
        """Save an auxiliary file into a snapshot directory. data is bytes or str."""
        ...

    @abstractmethod
    def save_artifact_file(self, app_name, verstr, src_path):
        """Copy an artifact file into the snapshot's artifacts subdirectory."""
        ...

    @abstractmethod
    def list_artifact_files(self, app_name, verstr):
        """Return the filesystem path to the artifacts directory, or None."""
        ...

    def list_artifacts(self, app_name, verstr):
        """``[{"name", "size"}]`` for the record's artifacts, name-ordered."""
        art_dir = self.list_artifact_files(app_name, verstr)
        if not art_dir or not os.path.isdir(art_dir):
            return []
        return [
            {"name": name, "size": os.path.getsize(os.path.join(art_dir, name))}
            for name in sorted(os.listdir(art_dir))
            if os.path.isfile(os.path.join(art_dir, name))
        ]

    def artifact_local_path(self, app_name, verstr, name):
        """A local path to artifact *name*, or None (unknown or unsafe name)."""
        if not valid_artifact_name(name):
            return None
        art_dir = self.list_artifact_files(app_name, verstr)
        path = os.path.join(art_dir, name) if art_dir else None
        return path if path and os.path.isfile(path) else None

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        """Append a single log entry to the writer's per-writer log file.
        Default implementation falls back to read-modify-write on log.yml."""
        data = self.load_file(app_name, verstr, LEGACY_LOG_FILE)
        log = yaml_safe_load(data) if data else []
        log.append(entry)
        self.save_file(
            app_name, verstr, LEGACY_LOG_FILE, yaml.dump(log, sort_keys=False)
        )

    def load_logs_by_writer(self, app_name, verstr):
        """``{writer: [entries]}``; the legacy ``log.yml`` is writer ``""``."""
        return {"": self.load_merged_log(app_name, verstr)}

    def load_merged_log(self, app_name, verstr):
        """Load and merge all per-writer log files plus legacy log.yml.
        Default implementation reads only log.yml."""
        data = self.load_file(app_name, verstr, LEGACY_LOG_FILE)
        if data is None:
            return []
        loaded = yaml_safe_load(data)
        return loaded if isinstance(loaded, list) else []

    def log_sizes(self, app_name, verstr):
        """``{writer: bytes}`` of the record's logs (``""`` = legacy ``log.yml``).

        A writer's log only ever grows, so comparing sizes tells which copy of
        it is newer without reading either. Empty when the backend can't tell.
        """
        return {}

    def log_objects(self, app_name, verstr, writer_id):
        """``[(object name, size)]`` of a writer's remote log objects, in order."""
        return []

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        """Sync the writer's log file to remote storage. No-op by default."""
