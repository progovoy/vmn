#!/usr/bin/env python3
"""Rebuilding a SQLite cache file without deleting it under its readers
(plan 25 §2).

A cache database has a *logical* path ``<dir>/<name><ext>``. Until its
first rebuild the file at that path is the database. A rebuild (or a
corruption recovery) writes a new generation ``<dir>/<name>.<n><ext>`` and
atomically replaces the pointer file ``<dir>/<name><ext>.current``, which
names the live one; every open reads the pointer. Files no longer live are
removed by :func:`sweep` only when no connection holds them: SQLite keeps a
shared lock on a database file for as long as a connection has it open, so
an exclusive lock that succeeds proves nobody does.
"""
import os
import re
import sqlite3

from vmn_exp.storage.files import atomic_write

POINTER_SUFFIX = ".current"
_SIDE_FILES = ("-wal", "-shm", "-journal")


def is_file_path(path):
    return bool(path) and path != ":memory:" and not path.startswith("file:")


def _pointer(path):
    return path + POINTER_SUFFIX


def live_path(path):
    """The file now holding the database whose logical path is *path*."""
    if not is_file_path(path):
        return path
    try:
        with open(_pointer(path)) as f:
            name = f.read().strip()
    except OSError:
        return path
    return os.path.join(os.path.dirname(path), name) if name else path


def pointer_stamp(path):
    """Changes whenever *path*'s pointer is flipped; None without one."""
    if not is_file_path(path):
        return None
    try:
        st = os.stat(_pointer(path))
    except OSError:
        return None
    return st.st_ino, st.st_mtime_ns, st.st_size


def _generations(path):
    """``{n: file}`` of *path*'s generation files on disk."""
    stem, ext = os.path.splitext(path)
    folder, base = os.path.split(stem)
    pattern = re.compile(re.escape(base) + r"\.(\d+)" + re.escape(ext) + "$")
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return {}
    matches = ((pattern.match(name), name) for name in names)
    return {int(m.group(1)): os.path.join(folder, name) for m, name in matches if m}


def new_generation(path):
    """A new, empty generation file of *path*, created exclusively (two
    rebuilders never share one)."""
    stem, ext = os.path.splitext(path)
    n = max(_generations(path), default=0) + 1
    while True:
        candidate = f"{stem}.{n}{ext}"
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return candidate
        except FileExistsError:
            n += 1


def flip(path, target):
    """Make *target* (a generation file beside *path*) the live database."""
    atomic_write(_pointer(path), os.path.basename(target) + "\n")


def _all_files(path):
    return [path, *_generations(path).values()]


def sweep(path):
    """Remove every file of *path*'s database but the live one, when unused."""
    live = live_path(path)
    for file in _all_files(path):
        if file != live:
            remove_if_unused(file)


def drop(path):
    """Remove every unused file of *path*'s database, and its pointer."""
    for file in _all_files(path):
        remove_if_unused(file)
    try:
        os.remove(_pointer(path))
    except OSError:
        pass


def remove_if_unused(file):
    """Delete *file* (with its WAL and shared memory) unless a connection
    holds it; True when it is gone."""
    if not os.path.exists(file):
        _remove_side_files(file)
        return True
    probe = None
    try:
        probe = sqlite3.connect(f"file:{file}?mode=rw", uri=True, timeout=0,
                                isolation_level=None)
        probe.execute("PRAGMA locking_mode=EXCLUSIVE")
        probe.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError:
        if probe is not None:
            probe.close()
        return False  # held (locked), or unopenable here: leave it
    except sqlite3.DatabaseError:
        pass  # not a database: no connection can be using it
    try:
        os.remove(file)
    except OSError:
        return False
    finally:
        if probe is not None:
            probe.close()
    _remove_side_files(file)  # in case closing the probe left any behind
    return True


def _remove_side_files(file):
    for suffix in _SIDE_FILES:
        try:
            os.remove(file + suffix)
        except OSError:
            pass
