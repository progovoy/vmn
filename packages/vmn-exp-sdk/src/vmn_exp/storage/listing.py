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
A record's ``log/`` and ``metrics/`` folders count as part of it: their files
list as ``log/<name>``/``metrics/<name>`` and their own ``(mtime, inode)``
join the record's signature. Asked for their *identity* (as a local-first
cache over a local root and an index's I/O helper ask: the cache's merge may
rewrite a local log), log files also carry their inode and their folder's mtime
(:func:`~vmn_exp.core.logfiles.local_log_sig`) — no extra syscall on a
re-listing, one stat of ``log/`` on a scan.

A listing of at least ``PARALLEL_MIN_DIRS`` directories spreads them over
threads (:func:`map_dirs`): every scandir/stat releases the GIL, so their
syscalls overlap (a cold listing of 100k records went from ~19s to ~5s).
"""
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.core.logfiles import LOG_DIR, local_log_sig
from vmn_exp.core.metric_files import METRICS_DIR

_COARSE_SETTLED_NS = 2 * 10**9  # FAT's mtime granularity
_FINE_SETTLED_NS = 10**8  # well past exFAT's 10ms and a coarse kernel clock tick
PARALLEL_MIN_DIRS = 2000
_THREADS = 16
_SUBDIRS = (LOG_DIR, METRICS_DIR)
_LOG_AT = _SUBDIRS.index(LOG_DIR)
_LOG_PREFIX = LOG_DIR + "/"


def map_dirs(fn, items):
    """``[fn(item) for item in items]``, on threads when there are many."""
    if len(items) < PARALLEL_MIN_DIRS:
        return list(map(fn, items))
    # By hand: a thread pool's map ignores chunksize (a future per item).
    size = -(-len(items) // (_THREADS * 4))
    chunks = [items[i : i + size] for i in range(0, len(items), size)]
    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        return [out for part in pool.map(lambda c: list(map(fn, c)), chunks) for out in part]


def _sig(st, log_mtime_ns=None):
    """A file's signature: a log file's with its identity when *log_mtime_ns*
    (its folder's mtime) is given."""
    if log_mtime_ns is None:
        return st.st_size, st.st_mtime_ns
    return local_log_sig(st, log_mtime_ns)


def _scan_files(path, prefix="", log_mtime_ns=None):
    files = {}
    for f in os.scandir(path):
        if f.is_file() and not f.name.startswith("."):
            files[prefix + f.name] = _sig(f.stat(), log_mtime_ns)
    return files


def files_in(path, identity=False):
    """``{filename: (size, mtime_ns)}`` of the regular, non-hidden files in
    *path* and in its ``log/`` and ``metrics/`` folders (named ``log/<file>``,
    ``metrics/<file>``); with *identity*, a log file's signature is
    :func:`~vmn_exp.core.logfiles.local_log_sig`'s."""
    log_sig = _dir_sig(os.path.join(path, LOG_DIR)) if identity else None
    return _files_in(path, log_sig[0] if log_sig else None)


def _files_in(path, log_mtime_ns):
    files = _scan_files(path)
    for sub in _SUBDIRS:
        mtime_ns = log_mtime_ns if sub == LOG_DIR else None
        try:
            files.update(_scan_files(os.path.join(path, sub), sub + "/", mtime_ns))
        except (FileNotFoundError, NotADirectoryError):
            pass
    return files


def _dir_sig(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_ino


def _sub_sigs(path):
    return tuple(_dir_sig(os.path.join(path, sub)) for sub in _SUBDIRS)


def _settle_ns(mtime_ns):
    return _FINE_SETTLED_NS if mtime_ns % 10**9 else _COARSE_SETTLED_NS


def _stat_again(path, names, log_mtime_ns=None):
    """``files_in(path)`` for a directory known to hold exactly *names*, its
    ``log/`` folder (when *log_mtime_ns* is given) still at that mtime; None
    when one of them is gone or no longer a regular file."""
    files = {}
    for name in names:
        try:
            st = os.stat(os.path.join(path, name))
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(st.st_mode):
            return None
        in_log = name.startswith(_LOG_PREFIX)
        files[name] = _sig(st, log_mtime_ns if in_log else None)
    return files


class RecordListings:
    """The file names of each settled record directory at its last scan."""

    def __init__(self):
        self._settled = {}  # dir path -> ((mtime_ns, inode), [file names])

    def list_all(self, base, keep, scan=files_in, identity=False):
        """``{entry name: scan(entry)}`` for the directories in *base* whose
        files satisfy *keep* — with :func:`files_in`'s *identity*. The
        stat-only shortcut applies to the default *scan* alone: a storage
        listing its files its own way is always asked."""
        entries = [entry for entry in os.scandir(base) if entry.is_dir()]
        settled = {}

        def files_of(entry):
            return self._files_of(entry, settled, scan, identity)

        found = map_dirs(files_of, entries)
        listed = {e.name: files for e, files in zip(entries, found) if keep(files)}
        self._settled = settled  # removed records drop out
        return listed

    def _files_of(self, entry, settled, scan, identity):
        if scan is not files_in:
            return scan(entry.path)
        st = entry.stat()  # before the scan: a change racing it moves the sig
        sub_sigs = _sub_sigs(entry.path)
        sig = (st.st_mtime_ns, st.st_ino, sub_sigs)
        log_sig = sub_sigs[_LOG_AT] if identity else None
        log_mtime_ns = log_sig[0] if log_sig else None
        known = self._settled.get(entry.path)
        files = None
        if known and known[0] == sig:
            files = _stat_again(entry.path, known[1], log_mtime_ns)
        if files is None:
            scanned_at = time.time_ns()
            if log_mtime_ns is None:
                files = files_in(entry.path)
            else:
                files = _files_in(entry.path, log_mtime_ns)
            mtime_ns = max([st.st_mtime_ns] + [sub[0] for sub in sub_sigs if sub])
            if mtime_ns > scanned_at - _settle_ns(mtime_ns):
                return files
        settled[entry.path] = (sig, list(files))
        return files
