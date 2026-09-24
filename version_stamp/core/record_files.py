#!/usr/bin/env python3
"""Reads of a local record's files — the one definition, shared by the local
storage backend and the experiment index's worker processes, so both see a
missing or special file the same way."""
import os


def read_file(path):
    """The bytes of *path*, or None when it is not a regular file."""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def read_file_from(path, offset):
    """The bytes of *path* past *offset*, or None when it is missing."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read()
    except FileNotFoundError:
        return None


class RecordFiles:
    """The ``load_file``/``read_file_from`` of a local storage, given each
    record's directory — all an experiment index worker needs to load a record."""

    def __init__(self, dirs):
        self._dirs = dirs  # {record key: its directory}

    def load_file(self, app_name, key, filename):
        return read_file(os.path.join(self._dirs[key], filename))

    def read_file_from(self, app_name, key, filename, offset):
        return read_file_from(os.path.join(self._dirs[key], filename), offset)
