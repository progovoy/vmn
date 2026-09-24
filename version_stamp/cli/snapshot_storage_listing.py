#!/usr/bin/env python3
"""Full listings of local record directories, re-using settled ones.

Opening a directory costs about ten times a ``stat``, and a full listing —
what every index refresh pays — opens every record's. But a directory's
entries only change with its mtime (creating, removing or renaming an entry
bumps it; vmn's writes are all atomic renames), so a record whose ``(mtime,
inode)`` has not moved since it was last scanned holds the same files: they
are just stat-ed again, which still catches an in-place append.

A scan is only trusted once the directory's mtime is ``_SETTLED_NS`` older
than the scan: a filesystem with coarse timestamps can stamp a change right
after the scan with the very mtime it saw. A file gone behind an unchanged
signature, or no longer a regular file, sends the record back to a scan.
"""
import os
import stat
import time

_SETTLED_NS = 2 * 10**9  # FAT's mtime granularity; ext4/APFS/NFS are finer


def files_in(path):
    """``{filename: (size, mtime_ns)}`` of the regular, non-hidden files in *path*."""
    return {
        f.name: (f.stat().st_size, f.stat().st_mtime_ns)
        for f in os.scandir(path)
        if f.is_file() and not f.name.startswith(".")
    }


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

    def list_all(self, base, keep):
        """``{entry name: files_in(entry)}`` for the directories in *base*
        whose files satisfy *keep*."""
        listed, settled = {}, {}
        for entry in os.scandir(base):
            if entry.is_dir():
                files = self._files_of(entry, settled)
                if keep(files):
                    listed[entry.name] = files
        self._settled = settled  # removed records drop out
        return listed

    def _files_of(self, entry, settled):
        st = entry.stat()  # before the scan: a change racing it moves the sig
        sig = (st.st_mtime_ns, st.st_ino)
        known = self._settled.get(entry.path)
        files = _stat_again(entry.path, known[1]) if known and known[0] == sig else None
        if files is None:
            scanned_at = time.time_ns()
            files = files_in(entry.path)
            if st.st_mtime_ns > scanned_at - _SETTLED_NS:
                return files
        settled[entry.path] = (sig, list(files))
        return files
