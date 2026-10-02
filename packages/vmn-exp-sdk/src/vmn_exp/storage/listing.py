#!/usr/bin/env python3
"""Full listings of local record directories, re-using settled ones.

Opening a directory costs about ten times a ``stat``, and a full listing —
what every index refresh pays — opens every record's. But a directory's
entries only change with its mtime (creating, removing or renaming an entry
bumps it; vmn's writes are all atomic renames), so a record whose ``(mtime,
inode)`` has not moved since it was last scanned holds the same files: they
are just stat-ed again, which still catches an in-place append.

A scan is only trusted once the directory's mtime is older than the scan by
the filesystem's timestamp granularity: one with coarse timestamps can stamp a
change right after the scan with the very mtime it saw. A whole-second mtime
waits ``_COARSE_SETTLED_NS``; one with sub-second digits comes from a finer
filesystem (whose clock may still tick every few ms) and waits
``_FINE_SETTLED_NS``. A file gone behind an unchanged
signature, or no longer a regular file, sends the record back to a scan.
A record's ``log/`` folder counts as part of it: its files list as
``log/<name>`` and its own ``(mtime, inode)`` joins the record's signature.

A listing of at least ``PARALLEL_MIN_DIRS`` directories spreads them over
threads (:func:`map_dirs`): every scandir/stat releases the GIL, so their
syscalls overlap (a cold listing of 100k records went from ~19s to ~5s).
"""
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.core.logfiles import LOG_DIR

_COARSE_SETTLED_NS = 2 * 10**9  # FAT's mtime granularity
_FINE_SETTLED_NS = 10**8  # well past exFAT's 10ms and a coarse kernel clock tick
PARALLEL_MIN_DIRS = 2000
_THREADS = 16


def map_dirs(fn, items):
    """``[fn(item) for item in items]``, on threads when there are many."""
    if len(items) < PARALLEL_MIN_DIRS:
        return list(map(fn, items))
    # By hand: a thread pool's map ignores chunksize (a future per item).
    size = -(-len(items) // (_THREADS * 4))
    chunks = [items[i : i + size] for i in range(0, len(items), size)]
    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        return [out for part in pool.map(lambda c: list(map(fn, c)), chunks) for out in part]


def _scan_files(path, prefix=""):
    files = {}
    for f in os.scandir(path):
        if f.is_file() and not f.name.startswith("."):
            st = f.stat()
            files[prefix + f.name] = (st.st_size, st.st_mtime_ns)
    return files


def files_in(path):
    """``{filename: (size, mtime_ns)}`` of the regular, non-hidden files in
    *path* and in its ``log/`` folder (named ``log/<file>``)."""
    files = _scan_files(path)
    try:
        files.update(_scan_files(os.path.join(path, LOG_DIR), LOG_DIR + "/"))
    except (FileNotFoundError, NotADirectoryError):
        pass
    return files


def _log_dir_sig(path):
    try:
        st = os.stat(os.path.join(path, LOG_DIR))
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_ino


def _settle_ns(mtime_ns):
    return _FINE_SETTLED_NS if mtime_ns % 10**9 else _COARSE_SETTLED_NS


def _stat_again(path, names):
    """``files_in(path)`` for a directory known to hold exactly *names*;
    None when one of them is gone or no longer a regular file."""
    files = {}
    for name in names:
        try:
            st = os.stat(os.path.join(path, name))
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(st.st_mode):
            return None
        files[name] = (st.st_size, st.st_mtime_ns)
    return files


class RecordListings:
    """The file names of each settled record directory at its last scan."""

    def __init__(self):
        self._settled = {}  # dir path -> ((mtime_ns, inode), [file names])

    def list_all(self, base, keep, scan=files_in):
        """``{entry name: scan(entry)}`` for the directories in *base* whose
        files satisfy *keep*. The stat-only shortcut applies to the default
        *scan* alone: a storage listing its files its own way is always asked."""
        entries = [entry for entry in os.scandir(base) if entry.is_dir()]
        settled = {}

        found = map_dirs(lambda entry: self._files_of(entry, settled, scan), entries)
        listed = {e.name: files for e, files in zip(entries, found) if keep(files)}
        self._settled = settled  # removed records drop out
        return listed

    def _files_of(self, entry, settled, scan):
        if scan is not files_in:
            return scan(entry.path)
        st = entry.stat()  # before the scan: a change racing it moves the sig
        log_sig = _log_dir_sig(entry.path)
        sig = (st.st_mtime_ns, st.st_ino, log_sig)
        known = self._settled.get(entry.path)
        files = _stat_again(entry.path, known[1]) if known and known[0] == sig else None
        if files is None:
            scanned_at = time.time_ns()
            files = files_in(entry.path)
            mtime_ns = max(st.st_mtime_ns, log_sig[0] if log_sig else 0)
            if mtime_ns > scanned_at - _settle_ns(mtime_ns):
                return files
        settled[entry.path] = (sig, list(files))
        return files
