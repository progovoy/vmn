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

from vmn_exp._base import parse_record_metadata
from vmn_exp.core.code_store import resolve_code
from vmn_exp.core.record_format import readable
from vmn_exp.storage.files import (
    METADATA_FILE,
    apply_metadata_updates,
    artifact_file_path,
    list_record_artifacts,
    valid_artifact_path,
)


class SnapshotStorage(ABC):
    # The store area (:mod:`vmn_exp.storage.areas`) this storage reads/writes.
    area = None

    def in_area(self, name):
        """The storage of the same root's *name* area (opened once)."""
        if name == self.area:
            return self
        opened = self.__dict__.setdefault("_areas", {})
        if name not in opened:
            opened[name] = self._open_area(name)
        return opened[name]

    def _open_area(self, name):
        raise NotImplementedError(f"{type(self).__name__} has no store areas")

    @abstractmethod
    def save(self, app_name, verstr, metadata, patches):
        ...

    @abstractmethod
    def load_record(self, app_name, verstr):
        """``(metadata, the record's own patches)``, or ``(None, None)``."""
        ...

    def load(self, app_name, verstr):
        """``(metadata, patches)``: a run's patches come from its code object
        (:mod:`vmn_exp.core.code_store`)."""
        metadata, patches = self.load_record(app_name, verstr)
        return resolve_code(self, app_name, metadata, patches)

    @abstractmethod
    def list_snapshots(self, app_name):
        ...

    def list_verstrs(self, app_name):
        """Names only. Backends override this to avoid parsing any metadata."""
        return [m["verstr"] for m in self.list_snapshots(app_name)]

    def list_apps(self):
        """The names of the apps (scopes) with records here, sorted."""
        return sorted({self._app_name_of(key) for key in self._app_keys()})

    def _app_keys(self):
        """The raw per-app keys this backend stores records under."""
        return ()

    def _app_name_of(self, key):
        return key

    def load_metadata(self, app_name, verstr):
        """A record's metadata alone — no patches or tarball — or None (also
        for a record a newer format wrote)."""
        return self.readable(self._parsed_metadata(app_name, verstr), app_name, verstr)

    def _parsed_metadata(self, app_name, verstr):
        return parse_record_metadata(self.load_file(app_name, verstr, METADATA_FILE))

    def readable(self, metadata, app_name, verstr):
        """*metadata*, or None when a newer record format wrote it (warned
        about once per record by this storage)."""
        return readable(metadata, f"{app_name}/{verstr}", owner=self)

    def exists(self, app_name, verstr):
        """Check if a snapshot exists without loading its full content."""
        metadata, _ = self.load_record(app_name, verstr)
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

    def read_file_from(self, app_name, verstr, filename, offset):
        """*filename*'s bytes from *offset* on, or None when it is missing."""
        data = self.load_file(app_name, verstr, filename)
        return None if data is None else data[offset:]

    def is_remote(self):
        """Whether reads go over the network (so concurrent reads pay off)."""
        return False

    def index_cache_path(self, app_name):
        """Where a persistent experiment index for *app_name* may live, or None."""
        return None

    def cache_identity(self):
        """A hashable name for this backend's data, for process-wide caches."""
        return None

    @abstractmethod
    def update_note(self, app_name, verstr, note):
        ...

    def update_metadata(self, app_name, verstr, updates):
        """Merge *updates* into the record's metadata (a None value drops the
        field); False when there is no record. Backends override this with an
        atomic (local) or conditional (S3) rewrite."""
        metadata = self._parsed_metadata(app_name, verstr)
        if metadata is None:
            return False
        data = yaml.dump(apply_metadata_updates(metadata, updates), sort_keys=True)
        return self.save_file(app_name, verstr, METADATA_FILE, data) is not False

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
    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        """Copy a file into the record as *name* — its record-relative path,
        ``artifacts/<user path>`` or ``outputs/<path>`` (default:
        ``artifacts/<basename>``)."""
        ...

    @abstractmethod
    def local_record_dir(self, app_name, verstr):
        """The local directory holding the record's ``artifacts/`` and
        ``outputs/`` trees, or None."""
        ...

    def list_artifacts(self, app_name, verstr):
        """``[{"name", "size"}]`` for the record's stored files (user
        artifacts and vmn outputs), named by record-relative path."""
        record_dir = self.local_record_dir(app_name, verstr)
        if not record_dir or not os.path.isdir(record_dir):
            return []
        return list_record_artifacts(record_dir)

    def artifact_local_path(self, app_name, verstr, name):
        """A local path to stored file *name*, or None (unknown or unsafe name)."""
        if not valid_artifact_path(name):
            return None
        record_dir = self.local_record_dir(app_name, verstr)
        path = artifact_file_path(record_dir, name) if record_dir else None
        return path if path and os.path.isfile(path) else None

    def log_sizes(self, app_name, verstr):
        """``{writer: bytes}`` of the record's logs .

        A writer's log only ever grows, so comparing sizes tells which copy of
        it is newer without reading either. Empty when the backend can't tell.
        """
        return {}

    def log_objects(self, app_name, verstr, writer_id):
        """``[(object name, size)]`` of a writer's remote log objects, in order."""
        return []

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        """Sync the writer's log file to remote storage. No-op by default."""
