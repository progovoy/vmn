#!/usr/bin/env python3
"""The server's reads of a run's local record stay inside its record dir
(plan 42 E9b).

Anyone who can write into a shared file:// store or a git workspace can
replace a record file with a symlink to any file the server user can read
(server.yml, the control-plane database, ``/proc/self/environ``). Served
through :class:`ContainedReads`, a named read whose real path leaves the
record dir answers as a missing file, and the artifact listing leaves such
files out. The record's file listing already skips them
(:func:`vmn_exp.storage.listing.files_in`), so the run list and the log parse
never see them. A backend with no local record dir (an object store, the S3
download cache) is passed through: the server fetched those files itself.

Job-side reads are not wrapped: a run that links a large checkpoint into its
artifacts still reads it back.
"""
import os

from vmn_exp.storage.files import METADATA_FILE, artifact_file_path


class ContainedReads:
    """*storage* for serving; *realpath* resolves a local path's symlinks."""

    def __init__(self, storage, realpath):
        self._storage = storage
        self._realpath = realpath

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def _contained(self, app_name, verstr, name):
        """Whether record file *name* resolves inside the record dir (or the
        backend has none)."""
        record_dir = self._storage.local_record_dir(app_name, verstr)
        if record_dir is None:
            return True
        base = self._realpath(record_dir)
        real = self._realpath(artifact_file_path(record_dir, name))
        try:
            return os.path.commonpath([base, real]) == base
        except ValueError:  # different drives on Windows
            return False

    def _read(self, read, app_name, verstr, name, *args):
        if not self._contained(app_name, verstr, name):
            return None
        return read(app_name, verstr, name, *args)

    def load_metadata(self, app_name, verstr):
        if not self._contained(app_name, verstr, METADATA_FILE):
            return None
        return self._storage.load_metadata(app_name, verstr)

    def load_file(self, app_name, verstr, name):
        return self._read(self._storage.load_file, app_name, verstr, name)

    def read_range(self, app_name, verstr, name, offset, length):
        return self._read(self._storage.read_range, app_name, verstr, name, offset, length)

    def read_file_from(self, app_name, verstr, name, offset):
        return self._read(self._storage.read_file_from, app_name, verstr, name, offset)

    def artifact_local_path(self, app_name, verstr, name):
        return self._read(self._storage.artifact_local_path, app_name, verstr, name)

    def list_artifacts(self, app_name, verstr):
        return [a for a in self._storage.list_artifacts(app_name, verstr)
                if self._contained(app_name, verstr, a["name"])]
