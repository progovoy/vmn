#!/usr/bin/env python3
"""The local-disk backend: ``<root>/<area>/<app key>/<verstr>/``."""
import json
import os
import shutil
from pathlib import Path

import yaml

from vmn_exp import _base
from vmn_exp._base import VMN_LOGGER, parse_record_metadata
from vmn_exp.core.record_format import with_format_version
from vmn_exp.core.record_files import read_file, read_file_from
from vmn_exp.storage.areas import SNAPSHOTS, app_key, app_name_of
from vmn_exp.storage.base import SnapshotStorage
from vmn_exp.storage import host_dirs
from vmn_exp.storage.files import (
    METADATA_FILE,
    apply_metadata_updates,
    artifact_file_path,
    artifact_name_for,
    atomic_write,
    checked_app_path,
    merged_log,
    group_log_names,
    log_object_name,
    log_sizes_of,
    parse_jsonl,
    read_patches_from_dir,
    safe_dep_name,
    safe_verstr,
    unsafe_verstr,
    write_patches_to_dir,
)
from vmn_exp.storage.local_metrics import LocalMetrics
from vmn_exp.storage.listing import RecordListings, files_in, map_dirs


def _ensure_parent(path):
    """Create *path*'s folder inside its record (``log/``); never the record
    itself, so a record deleted under a writer stays deleted."""
    try:
        os.mkdir(os.path.dirname(path))
    except FileExistsError:
        pass


def _append_bytes(path, text):
    """Append *text* with a single ``O_APPEND`` write (looping only on a short one)."""
    data = text.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
    try:
        while data:
            data = data[os.write(fd, data) :]
    finally:
        os.close(fd)


def _read_class(storage):
    """The class whose reads *storage* does (a journaled store journals its
    writes only, so it reads as the backend it wraps)."""
    return getattr(type(storage), "read_class", type(storage))


def _dir_sig(entry):
    """A record directory's ``(mtime_ns, inode)``: every atomic write bumps it."""
    return (entry.stat().st_mtime_ns, entry.inode())


class LocalSnapshotStorage(LocalMetrics, SnapshotStorage):
    def __init__(self, root, area=SNAPSHOTS):
        self.root = root
        self.area = area
        self._listings = RecordListings()
        self._identity = None

    def _open_area(self, name):
        return LocalSnapshotStorage(self.root, name)

    def _area_dir(self):
        return os.path.join(self.root, self.area)

    def _snapshot_base_dir(self, app_name):
        return os.path.join(self._area_dir(), app_key(checked_app_path(app_name)))

    def _snapshot_dir(self, app_name, verstr):
        return os.path.join(self._snapshot_base_dir(app_name), safe_verstr(verstr))

    def _ensure_base_dir(self, app_name):
        """The base dir, under a root whose one ``.gitignore`` ignores it all."""
        base = self._snapshot_base_dir(app_name)
        Path(base).mkdir(parents=True, exist_ok=True)
        ignore = os.path.join(self.root, ".gitignore")
        if not os.path.exists(ignore):
            atomic_write(ignore, "*\n")
        return base

    def _has_record(self, app_name, verstr):
        return os.path.isfile(
            os.path.join(self._snapshot_dir(app_name, verstr), METADATA_FILE)
        )

    def exists(self, app_name, verstr):
        try:
            return self._has_record(app_name, verstr)
        except ValueError:
            return False  # not a record name, so certainly no record

    def save(self, app_name, verstr, metadata, patches):
        self._ensure_base_dir(app_name)
        snap_dir = self._snapshot_dir(app_name, verstr)
        Path(snap_dir).mkdir(exist_ok=True)
        self._write_record(app_name, verstr, snap_dir, metadata, patches)

    def create_exclusive(self, app_name, verstr, metadata, patches):
        self._ensure_base_dir(app_name)
        snap_dir = self._snapshot_dir(app_name, verstr)
        try:
            os.mkdir(snap_dir)  # the claim: exactly one creator succeeds
        except FileExistsError:
            return False
        self._write_record(app_name, verstr, snap_dir, metadata, patches)
        return True

    def _write_record(self, app_name, verstr, snap_dir, metadata, patches):
        write_patches_to_dir(snap_dir, patches)
        for dep_path, dep_patches in patches.get("deps", {}).items():
            dep_dir = os.path.join(snap_dir, "deps", safe_dep_name(dep_path))
            Path(dep_dir).mkdir(parents=True, exist_ok=True)
            write_patches_to_dir(dep_dir, dep_patches)
        # Last: metadata.yml is what makes the record visible.
        atomic_write(
            os.path.join(snap_dir, METADATA_FILE),
            yaml.dump(with_format_version(metadata), sort_keys=True),
        )

    def _load_metadata(self, meta_path):
        with open(meta_path, "rb") as f:
            return _base.yaml_safe_load(f)

    def load_record(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        meta_path = os.path.join(snap_dir, METADATA_FILE)
        if not os.path.isfile(meta_path):
            return None, None

        metadata = self._load_metadata(meta_path)
        patches = read_patches_from_dir(snap_dir)

        deps_dir = os.path.join(snap_dir, "deps")
        if os.path.isdir(deps_dir):
            dep_patches = {}
            for dep_name in os.listdir(deps_dir):
                dep_dir = os.path.join(deps_dir, dep_name)
                if os.path.isdir(dep_dir):
                    dp = read_patches_from_dir(dep_dir)
                    if dp:
                        dep_patches[dep_name] = dp
            if dep_patches:
                patches["deps"] = dep_patches

        return metadata, patches

    def _record_dirs(self, app_name):
        base = self._snapshot_base_dir(app_name)
        if not os.path.isdir(base):
            return []
        return [
            entry
            for entry in os.scandir(base)
            if entry.is_dir()
            and os.path.isfile(os.path.join(entry.path, METADATA_FILE))
        ]

    def _app_keys(self):
        area_dir = self._area_dir()
        if not os.path.isdir(area_dir):
            return []
        return [e.name for e in os.scandir(area_dir)
                if e.is_dir() and not e.name.startswith(".")]

    def _app_name_of(self, key):
        return app_name_of(key)

    def list_verstrs(self, app_name):
        return [unsafe_verstr(entry.name) for entry in self._record_dirs(app_name)]

    def list_snapshots(self, app_name):
        results = []
        for entry in self._record_dirs(app_name):
            meta_path = os.path.join(entry.path, METADATA_FILE)
            with open(meta_path, "rb") as f:
                meta = parse_record_metadata(f.read())
            if meta is None:
                VMN_LOGGER.debug(f"Skipping non-snapshot metadata: {meta_path}")
                continue
            if self.readable(meta, app_name, meta["verstr"]) is not None:
                results.append(meta)
        results.sort(key=lambda m: m.get("timestamp", ""))
        return results

    def list_record_names(self, app_name):
        """``{record key: (dir mtime_ns, inode)}`` from one directory listing.

        Every write into a record is atomic (temp file + rename), which bumps
        the record directory's mtime, and ``append_log_entry`` bumps it too.
        """
        base = self._snapshot_base_dir(app_name)
        if not os.path.isdir(base):
            return {}
        entries = [e for e in os.scandir(base) if e.is_dir() and not e.name.startswith(".")]
        sigs = map_dirs(_dir_sig, entries)
        return {unsafe_verstr(entry.name): sig for entry, sig in zip(entries, sigs)}

    def list_files(self, app_name, keys=None):
        """``{verstr: {filename: (size, mtime_ns)}}``; only *keys* when given
        (a key without a record is left out)."""
        if keys is None:
            return self._list_all_files(app_name)
        keys = list(keys)
        found = map_dirs(lambda key: self.record_files(app_name, key), keys)
        return {key: names for key, names in zip(keys, found) if METADATA_FILE in names}

    def _list_all_files(self, app_name):
        # The same records as _record_dirs, without stat-ing metadata.yml twice.
        base = self._snapshot_base_dir(app_name)
        if not os.path.isdir(base):
            return {}
        listed = self._listings.list_all(
            base, lambda files: METADATA_FILE in files, scan=self._files_in
        )
        return {unsafe_verstr(name): files for name, files in listed.items()}

    _files_in = staticmethod(files_in)

    def direct_files(self):
        return self

    def read_file_from(self, app_name, verstr, filename, offset):
        path = os.path.join(self._snapshot_dir(app_name, verstr), filename)
        return read_file_from(path, offset)

    def plain_record_dir(self, app_name, verstr):
        """The directory of *verstr*'s files, for a reader that opens them
        itself (the index's worker processes); None from a subclass, which
        may read its files some other way."""
        if _read_class(self) is not LocalSnapshotStorage:
            return None
        return self._snapshot_dir(app_name, verstr)

    def io_process_args(self):
        """``LocalSnapshotStorage(*args)`` in another process reads the same
        records (an index's I/O helper); None from a subclass, which may read
        its files some other way."""
        if _read_class(self) is not LocalSnapshotStorage:
            return None
        return (self.root, self.area)

    def cache_identity(self):
        # Resolved once: every index lookup asks, and realpath lstat-s each
        # path component.
        if self._identity is None:
            self._identity = ("local", os.path.realpath(self.root), self.area)
        return self._identity

    def index_cache_path(self, app_name):
        """In the per-host cache dir; None before any record."""
        if not os.path.isdir(self._snapshot_base_dir(app_name)):
            return None
        return host_dirs.index_cache_path(self.cache_identity(), app_name)

    def update_note(self, app_name, verstr, note):
        return self.update_metadata(app_name, verstr, {"note": note})

    def update_metadata(self, app_name, verstr, updates):
        """Merge *updates* into ``metadata.yml`` atomically (None drops a field)."""
        meta_path = os.path.join(self._snapshot_dir(app_name, verstr), METADATA_FILE)
        if not os.path.isfile(meta_path):
            return False
        metadata = apply_metadata_updates(self._load_metadata(meta_path), updates)
        atomic_write(meta_path, yaml.dump(metadata, sort_keys=True))
        return True

    def delete(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        if os.path.isdir(snap_dir):
            shutil.rmtree(snap_dir, ignore_errors=True)

    def load_file(self, app_name, verstr, filename):
        return read_file(os.path.join(self._snapshot_dir(app_name, verstr), filename))

    def _refuse_orphan_write(self, app_name, verstr, what):
        """A write into a record that does not exist (pruned, never created)
        must not bring its directory back as an invisible zombie."""
        if self._has_record(app_name, verstr):
            return False
        VMN_LOGGER.debug(f"Not writing {what}: {app_name} {verstr} does not exist")
        return True

    def save_file(self, app_name, verstr, filename, data):
        if self._refuse_orphan_write(app_name, verstr, filename):
            return False
        path = os.path.join(self._snapshot_dir(app_name, verstr), filename)
        _ensure_parent(path)
        atomic_write(path, data)
        return True

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        name = artifact_name_for(src_path, name)
        if self._refuse_orphan_write(app_name, verstr, src_path):
            return False
        dest = artifact_file_path(self._snapshot_dir(app_name, verstr), name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src_path, dest)
        return True

    def local_record_dir(self, app_name, verstr):
        record_dir = self._snapshot_dir(app_name, verstr)
        return record_dir if os.path.isdir(record_dir) else None

    def artifact_uri(self, app_name, verstr, path):
        """Stable ``file://`` URI referencing artifact *path* for this record."""
        abs_path = artifact_file_path(self._snapshot_dir(app_name, verstr), path)
        return f"file://{abs_path}"

    def record_files(self, app_name, verstr):
        """``{filename: (size, mtime_ns)}`` for one record's files — one scandir."""
        try:
            return self._files_in(self._snapshot_dir(app_name, verstr))
        except FileNotFoundError:
            return {}

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        return self.append_log_entries(app_name, verstr, writer_id, [entry])

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        """Append *entries* as whole lines in one ``write``: a reader sees all
        of the batch or none of it, never half a line."""
        if not entries:
            return True
        if self._refuse_orphan_write(app_name, verstr, "a log entry"):
            return False
        snap_dir = self._snapshot_dir(app_name, verstr)
        data = "".join(json.dumps(e, default=str) + "\n" for e in entries)
        path = os.path.join(snap_dir, log_object_name(writer_id))
        _ensure_parent(path)
        _append_bytes(path, data)
        # An append leaves the dir mtime alone; bump it so the index's
        # record signature (list_record_names) sees the change.
        os.utime(snap_dir)
        return True

    def load_logs_by_writer(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        logs = {}
        if os.path.isdir(snap_dir):
            for writer, names in group_log_names(files_in(snap_dir)).items():
                entries = logs.setdefault(writer, [])
                for name in names:
                    with open(os.path.join(snap_dir, name), encoding="utf-8") as f:
                        entries.extend(parse_jsonl(f.read(), writer))
        return logs

    def log_sizes(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        if not os.path.isdir(snap_dir):
            return {}
        return log_sizes_of((name, sig[0]) for name, sig in files_in(snap_dir).items())

    def load_merged_log(self, app_name, verstr):
        return merged_log(self, app_name, verstr, self.load_logs_by_writer(app_name, verstr))
