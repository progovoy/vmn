#!/usr/bin/env python3
"""The local-disk snapshot/experiment backend: ``.vmn/<app>/<subdir>/<verstr>/``."""
import json
import os
import shutil
from pathlib import Path

import yaml

from version_stamp.cli.snapshot_storage import SnapshotStorage
from version_stamp.cli.snapshot_storage_files import (
    INDEX_CACHE_FILE,
    LEGACY_LOG_FILE,
    METADATA_FILE,
    atomic_write,
    flatten_logs,
    group_log_names,
    log_object_name,
    parse_jsonl,
    read_patches_from_dir,
    safe_dep_name,
    safe_verstr,
    unsafe_verstr,
    write_patches_to_dir,
)
from version_stamp.core import utils as core_utils
from version_stamp.core.logging import VMN_LOGGER


class LocalSnapshotStorage(SnapshotStorage):
    def __init__(self, vmn_root_path, subdir="snapshots"):
        self.vmn_root_path = vmn_root_path
        self._subdir = subdir

    def _snapshot_base_dir(self, app_name):
        return os.path.join(
            self.vmn_root_path, ".vmn", app_name.replace("/", os.sep), self._subdir
        )

    def _snapshot_dir(self, app_name, verstr):
        return os.path.join(self._snapshot_base_dir(app_name), safe_verstr(verstr))

    def _ensure_base_dir(self, app_name):
        """The base dir, ignoring itself: the repo-level rule vmn commits at
        init only matches one level deep, which misses ``root/svc`` apps."""
        base = self._snapshot_base_dir(app_name)
        Path(base).mkdir(parents=True, exist_ok=True)
        ignore = os.path.join(base, ".gitignore")
        if not os.path.exists(ignore):
            atomic_write(ignore, "*\n")
        return base

    def _has_record(self, app_name, verstr):
        return os.path.isfile(
            os.path.join(self._snapshot_dir(app_name, verstr), METADATA_FILE)
        )

    def exists(self, app_name, verstr):
        return self._has_record(app_name, verstr)

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

    def _same_code_dirs(self, app_name, verstr, metadata):
        """Sibling runs of the same code, whose patches may be shared."""
        code = (metadata or {}).get("code_verstr")
        if not code:
            return []
        base = self._snapshot_base_dir(app_name)
        own, code = safe_verstr(verstr), safe_verstr(code)
        return [
            os.path.join(base, name)
            for name in os.listdir(base)
            if name != own and (name == code or name.startswith(code + "."))
        ]

    def _write_record(self, app_name, verstr, snap_dir, metadata, patches):
        siblings = self._same_code_dirs(app_name, verstr, metadata)
        write_patches_to_dir(snap_dir, patches, link_from=siblings)
        for dep_path, dep_patches in patches.get("deps", {}).items():
            safe_dep = safe_dep_name(dep_path)
            dep_dir = os.path.join(snap_dir, "deps", safe_dep)
            Path(dep_dir).mkdir(parents=True, exist_ok=True)
            dep_sources = [os.path.join(s, "deps", safe_dep) for s in siblings]
            write_patches_to_dir(dep_dir, dep_patches, link_from=dep_sources)
        # Last: metadata.yml is what makes the record visible.
        atomic_write(
            os.path.join(snap_dir, METADATA_FILE), yaml.dump(metadata, sort_keys=True)
        )

    def _load_metadata(self, meta_path):
        with open(meta_path, "rb") as f:
            return core_utils.yaml_safe_load(f)

    def load(self, app_name, verstr):
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

    def list_verstrs(self, app_name):
        return [unsafe_verstr(entry.name) for entry in self._record_dirs(app_name)]

    def list_snapshots(self, app_name):
        results = []
        for entry in self._record_dirs(app_name):
            meta_path = os.path.join(entry.path, METADATA_FILE)
            meta = self._load_metadata(meta_path)
            if not isinstance(meta, dict) or "verstr" not in meta:
                # Legacy create_snapshots verinfo files share this tree.
                VMN_LOGGER.debug(f"Skipping non-snapshot metadata: {meta_path}")
                continue
            results.append(meta)
        results.sort(key=lambda m: m.get("timestamp", ""))
        return results

    def list_files(self, app_name):
        files = {}
        for entry in self._record_dirs(app_name):
            files[unsafe_verstr(entry.name)] = {
                f.name: (f.stat().st_size, f.stat().st_mtime_ns)
                for f in os.scandir(entry.path)
                if f.is_file() and not f.name.startswith(".")
            }
        return files

    def direct_files(self):
        return self

    def read_file_from(self, app_name, verstr, filename, offset):
        path = os.path.join(self._snapshot_dir(app_name, verstr), filename)
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                return f.read()
        except FileNotFoundError:
            return None

    def cache_identity(self):
        return ("local", os.path.realpath(self.vmn_root_path), self._subdir)

    def index_cache_path(self, app_name):
        """Inside the base dir, which ignores itself; None before any record."""
        if not os.path.isdir(self._snapshot_base_dir(app_name)):
            return None
        return os.path.join(self._ensure_base_dir(app_name), INDEX_CACHE_FILE)

    def update_note(self, app_name, verstr, note):
        meta_path = os.path.join(self._snapshot_dir(app_name, verstr), METADATA_FILE)
        if not os.path.isfile(meta_path):
            return False
        metadata = self._load_metadata(meta_path)
        metadata["note"] = note
        atomic_write(meta_path, yaml.dump(metadata, sort_keys=True))
        return True

    def delete(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        if os.path.isdir(snap_dir):
            shutil.rmtree(snap_dir, ignore_errors=True)

    def load_file(self, app_name, verstr, filename):
        path = os.path.join(self._snapshot_dir(app_name, verstr), filename)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

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
        atomic_write(os.path.join(self._snapshot_dir(app_name, verstr), filename), data)
        return True

    def save_artifact_file(self, app_name, verstr, src_path):
        if self._refuse_orphan_write(app_name, verstr, src_path):
            return False
        art_dir = os.path.join(self._snapshot_dir(app_name, verstr), "artifacts")
        os.makedirs(art_dir, exist_ok=True)
        shutil.copy2(src_path, os.path.join(art_dir, os.path.basename(src_path)))
        return True

    def list_artifact_files(self, app_name, verstr):
        art_dir = os.path.join(self._snapshot_dir(app_name, verstr), "artifacts")
        if os.path.isdir(art_dir):
            return art_dir
        return None

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        if self._refuse_orphan_write(app_name, verstr, "a log entry"):
            return False
        path = os.path.join(
            self._snapshot_dir(app_name, verstr), log_object_name(writer_id)
        )
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return True

    def load_logs_by_writer(self, app_name, verstr):
        snap_dir = self._snapshot_dir(app_name, verstr)
        logs = {}
        legacy_path = os.path.join(snap_dir, LEGACY_LOG_FILE)
        if os.path.isfile(legacy_path):
            with open(legacy_path, "rb") as f:
                data = core_utils.yaml_safe_load(f)
            if isinstance(data, list):
                logs[""] = data
        if os.path.isdir(snap_dir):
            for writer, names in group_log_names(os.listdir(snap_dir)).items():
                entries = logs.setdefault(writer, [])
                for name in names:
                    with open(os.path.join(snap_dir, name), encoding="utf-8") as f:
                        entries.extend(parse_jsonl(f.read(), writer))
        return logs

    def load_merged_log(self, app_name, verstr):
        return flatten_logs(self.load_logs_by_writer(app_name, verstr))
