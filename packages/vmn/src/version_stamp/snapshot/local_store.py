"""The local record store: ``.vmn/<app>/<subdir>/<safe verstr>/``.

Writes the same bytes as ``vmn_exp.storage.local.LocalSnapshotStorage``: patch
files, ``deps/<safe dep>/`` patch files, then ``metadata.yml``
(``yaml.dump(sort_keys=True)``) last — it is what makes a record exist. The
base dir carries a ``.gitignore`` of ``*``. Every write is atomic.

``LocalRecordStore(vmn_root_path, subdir="snapshots", code_store=None)``:
  - ``save(app, verstr, metadata, patches)``
  - ``load_record(app, verstr) -> (metadata, patches) | (None, None)``
  - ``load(app, verstr)`` — like ``load_record`` with a ``code:`` reference
    resolved through *code_store* (default: this store)
  - ``load_metadata(app, verstr) -> dict | None`` (None for verinfo files)
  - ``exists``, ``list_verstrs``, ``list_record_names`` (names only),
    ``list_snapshots(app)`` (records, oldest ``timestamp`` first)
  - ``update_metadata(app, verstr, updates) -> bool`` (None drops a field),
    ``update_note``, ``delete``, ``load_file(app, verstr, name) -> bytes | None``
"""
import os
import shutil
from pathlib import Path

import yaml

from version_stamp.core.utils import (
    atomic_write,
    parse_record_metadata,
    valid_app_path,
    yaml_safe_load,
)
from version_stamp.snapshot.code_store import resolve_code
from version_stamp.snapshot.record import (
    METADATA_FILE,
    PATCH_FILES,
    safe_dep_name,
    safe_verstr,
    unsafe_verstr,
)


def _write_patches(directory, patches):
    """Write the patch files *patches* carries and drop the ones it lacks."""
    for key, filename, binary in PATCH_FILES:
        path = os.path.join(directory, filename)
        content = patches.get(key)
        if not content:
            if os.path.lexists(path):
                os.unlink(path)
            continue
        atomic_write(path, content if binary else content.encode("utf-8"))


def _read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _write_metadata(record_dir, metadata):
    atomic_write(os.path.join(record_dir, METADATA_FILE), yaml.dump(metadata, sort_keys=True))


def _read_patches(directory):
    patches = {}
    for key, filename, binary in PATCH_FILES:
        data = _read_file(os.path.join(directory, filename))
        if data is not None:
            patches[key] = data if binary else data.decode("utf-8")
    return patches


def _read_dep_patches(record_dir):
    deps_dir = os.path.join(record_dir, "deps")
    if not os.path.isdir(deps_dir):
        return {}
    found = {}
    for name in os.listdir(deps_dir):
        dep_dir = os.path.join(deps_dir, name)
        patches = _read_patches(dep_dir) if os.path.isdir(dep_dir) else None
        if patches:
            found[name] = patches
    return found


class LocalRecordStore:
    def __init__(self, vmn_root_path, subdir="snapshots", code_store=None):
        self.vmn_root_path = vmn_root_path
        self.subdir = subdir
        self.code_store = self if code_store is None else code_store

    def _base_dir(self, app_name):
        if not valid_app_path(app_name):
            raise ValueError(f"Invalid app name: {app_name!r}")
        return os.path.join(self.vmn_root_path, ".vmn", *app_name.split("/"), self.subdir)

    def _record_dir(self, app_name, verstr):
        return os.path.join(self._base_dir(app_name), safe_verstr(verstr))

    def _ensure_base_dir(self, app_name):
        base = self._base_dir(app_name)
        Path(base).mkdir(parents=True, exist_ok=True)
        ignore = os.path.join(base, ".gitignore")
        if not os.path.exists(ignore):
            atomic_write(ignore, "*\n")
        return base

    def save(self, app_name, verstr, metadata, patches):
        self._ensure_base_dir(app_name)
        record_dir = self._record_dir(app_name, verstr)
        Path(record_dir).mkdir(exist_ok=True)
        _write_patches(record_dir, patches)
        for dep_path, dep_patches in patches.get("deps", {}).items():
            dep_dir = os.path.join(record_dir, "deps", safe_dep_name(dep_path))
            Path(dep_dir).mkdir(parents=True, exist_ok=True)
            _write_patches(dep_dir, dep_patches)
        _write_metadata(record_dir, metadata)

    def load_file(self, app_name, verstr, filename):
        return _read_file(os.path.join(self._record_dir(app_name, verstr), filename))

    def load_metadata(self, app_name, verstr):
        return parse_record_metadata(self.load_file(app_name, verstr, METADATA_FILE))

    def load_record(self, app_name, verstr):
        record_dir = self._record_dir(app_name, verstr)
        raw = _read_file(os.path.join(record_dir, METADATA_FILE))
        if raw is None:
            return None, None
        patches = _read_patches(record_dir)
        deps = _read_dep_patches(record_dir)
        if deps:
            patches["deps"] = deps
        return yaml_safe_load(raw), patches

    def load(self, app_name, verstr):
        metadata, patches = self.load_record(app_name, verstr)
        return resolve_code(self.code_store, app_name, metadata, patches)

    def exists(self, app_name, verstr):
        try:
            return os.path.isfile(
                os.path.join(self._record_dir(app_name, verstr), METADATA_FILE)
            )
        except ValueError:
            return False

    def _record_dirs(self, app_name):
        base = self._base_dir(app_name)
        if not os.path.isdir(base):
            return []
        return [
            entry
            for entry in os.scandir(base)
            if entry.is_dir() and os.path.isfile(os.path.join(entry.path, METADATA_FILE))
        ]

    def list_verstrs(self, app_name):
        return [unsafe_verstr(entry.name) for entry in self._record_dirs(app_name)]

    list_record_names = list_verstrs

    def list_snapshots(self, app_name):
        found = (
            parse_record_metadata(_read_file(os.path.join(entry.path, METADATA_FILE)))
            for entry in self._record_dirs(app_name)
        )
        return sorted((m for m in found if m is not None), key=lambda m: m.get("timestamp", ""))

    def update_metadata(self, app_name, verstr, updates):
        record_dir = self._record_dir(app_name, verstr)
        raw = _read_file(os.path.join(record_dir, METADATA_FILE))
        if raw is None:
            return False
        metadata = yaml_safe_load(raw)
        for key, value in updates.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = value
        _write_metadata(record_dir, metadata)
        return True

    def update_note(self, app_name, verstr, note):
        return self.update_metadata(app_name, verstr, {"note": note})

    def delete(self, app_name, verstr):
        shutil.rmtree(self._record_dir(app_name, verstr), ignore_errors=True)
