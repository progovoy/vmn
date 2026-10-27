#!/usr/bin/env python3
"""Parsed experiment logs, kept across run-page polls.

A live run's page polls while its log grows. Re-reading the whole log each time
made a poll cost O(log); here a record's JSONL logs and metric streams are read
from the offset the last poll stopped at, and only the new entries are parsed,
appended to the series and folded into the params/metrics. A local root's files
grow in place; an object store's (S3, GCS, Azure) grow by new segment objects,
each written once, so a poll of a run alive for hours costs its listing plus the
segments shipped since the last poll — not a GET per segment it ever shipped.

The result is always what a full read gives. Each file's entries are kept, so
growth that reorders the merged log (an entry older than the newest one seen)
merges them again without reading anything; a shrunk or vanished file, one
rewritten other than by an append (a local root lists its log files with their
identity), a compaction or a seal is read again from scratch. A listed file
found missing (merged since the listing) costs one listing more
(:mod:`~vmn_exp.ui.readers.listed_reads`).

Entries are appended in place and each poll gets a :class:`LogSnapshot` that
sees a fixed prefix, so a slow response never observes a later poll's growth.
The cache is bounded by the log bytes it holds, not by a count of records.
"""
import threading
from collections import OrderedDict

from vmn_exp.core.fold import fold_log
from vmn_exp.core.jsonl_tail import UnterminatedEntry, read_complete_lines
from vmn_exp.core.log import load_log, metric_series
from vmn_exp.core.logfiles import is_log_file
from vmn_exp.core.media import MediaIndex
from vmn_exp.core.metric_files import is_indexed_file, is_metric_file
from vmn_exp.core.series_reader import indexed_entries, stream_entries
from vmn_exp.core.streams import display_writer
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.files import flatten_logs
from vmn_exp.ui.readers.listed_reads import ListedReads, StaleListing, read_each
from vmn_exp.ui.readers.log_snapshot import LogSnapshot
from vmn_exp.ui.readers.parsed_log_files import (
    appends_in_order,
    by_writer,
    merges,
    replaced,
    visible,
)
from vmn_exp.ui.readers.series import SeriesThinner

DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 1024  # a busy leaderboard reads hundreds of runs; the byte bound decides
MAX_THINNERS = 256

__all__ = ["LogSnapshot", "ParsedLogs"]


class _Parsed:
    """A record's growing parse: entries, per-metric series and the fold."""

    def __init__(self):
        self.entries, self.series, self.counts = [], {}, {}
        self.fold = fold_log([])
        self.media = MediaIndex()
        self.media_view = self.media.view()
        self.offsets = None  # {log file: bytes consumed} when incremental
        self.read = {}  # {log file: its entries read so far} when incremental
        self.sig = None
        self.snapshot = None
        self.thinners = {}  # (metric, max_points) -> SeriesThinner
        self.thin_lock = threading.Lock()

    def thinner(self, key, max_points):
        if len(self.thinners) > MAX_THINNERS:
            self.thinners.clear()
        return self.thinners.setdefault((key, max_points), SeriesThinner(max_points))

    def extend(self, new_entries):
        fold_log(new_entries, self.fold, start=len(self.entries))
        if self.media.add(new_entries):
            self.media_view = self.media.view()
        self.entries.extend(new_entries)
        for key, points in metric_series(new_entries).items():
            self.series.setdefault(key, []).extend(points)
            self.counts[key] = len(self.series[key])
        self.snapshot = LogSnapshot(self)
        return self


class _Pending(Exception):
    """A log ends in a complete line with no newline yet — read it fully."""


def _direct_files(storage):
    """Where *storage*'s per-file reads go: a local root or an object store;
    None for anything else (a plugin root may rewrite its files in place)."""
    direct = getattr(storage, "direct_files", None)
    files = direct() if direct else None
    if isinstance(files, LocalSnapshotStorage) or (files is not None and files.is_remote()):
        return files
    return None


def _log_files(storage, app_name, verstr):
    """``{log file: signature}`` of the record, or None when unknown — on an
    object store, from its log and metric listings alone."""
    list_files = getattr(storage, "stream_files", None) or getattr(storage, "record_files", None)
    files = list_files(app_name, verstr) if list_files else None
    if files is None:
        return None
    return {n: tuple(sig) for n, sig in files.items()
            if is_log_file(n) or is_metric_file(n)}


def _read_complete_lines(files_of, app_name, verstr, name, offset, writer):
    """``(entries, new offset)`` from *offset* up to the last newline."""
    try:
        read = read_complete_lines(
            files_of, app_name, verstr, name, offset, take_unterminated=False,
            errors="strict",
        )
    except UnterminatedEntry:
        raise _Pending() from None
    entries, used = read
    for entry in entries:
        entry["_writer"] = display_writer(writer)
    return entries, offset + used


def _read_stream(files_of, app_name, verstr, name, start, size):
    """``(metrics entries, new offset)`` of a stream's intact new blocks."""
    data = files_of.read_range(app_name, verstr, name, start, size - start)
    entries, used = stream_entries(data)
    return entries, start + used


def _read_file(files_of, app_name, verstr, item):
    """``(entries, new offset)`` of a listed file ``(stream, name, start,
    size)`` past *start*."""
    writer, name, start, size = item
    if is_log_file(name):
        return _read_complete_lines(files_of, app_name, verstr, name, start, writer)
    if is_indexed_file(name):
        entries, end = indexed_entries(files_of, app_name, verstr, name, size), size
    else:
        entries, end = _read_stream(files_of, app_name, verstr, name, start, size)
    return [dict(e, _writer=display_writer(writer)) for e in entries], end


def _read_all(files_of, app_name, verstr, items):
    """:func:`_read_file` of each item, in order; concurrent on a remote store."""
    read = lambda item: _read_file(files_of, app_name, verstr, item)  # noqa: E731
    if not files_of.is_remote():
        return [read(item) for item in items]
    return read_each(read, items, "vmn-ui-log-read")


def _read_growth(files_of, app_name, verstr, files, offsets):
    """``({file: new entries}, new offsets, visible groups)``, or None when
    not pure growth."""
    if any(name not in files or files[name][0] < end for name, end in offsets.items()):
        return None
    groups = visible(files)
    listed = [(w, n) for w, names in groups.items() for n in names]
    if offsets and any(merges(n) for _, n in listed if n not in offsets):
        return None  # compacted or sealed since: what it replaced restarts from 0
    items = [(w, n, offsets.get(n, 0), files[n][0])
             for w, n in listed if files[n][0] > offsets.get(n, 0)]
    reads = _read_all(files_of, app_name, verstr, items)
    new_offsets = dict(offsets)
    new_offsets.update((item[1], end) for item, (_, end) in zip(items, reads))
    return {item[1]: entries for item, (entries, _) in zip(items, reads)}, new_offsets, groups


def _grow(parsed, files_of, app_name, verstr, files):
    """*parsed* extended by the files' new bytes, or None to read afresh. New
    entries sorting before parsed ones make a new merge of the entries kept."""
    if replaced(parsed.sig, files, in_place=not files_of.is_remote()):
        return None
    found = _read_growth(files_of, app_name, verstr, files, parsed.offsets)
    if found is None:
        return None
    new, offsets, groups = found
    for name, entries in new.items():
        parsed.read.setdefault(name, []).extend(entries)
    new_entries = flatten_logs(by_writer(groups, new))
    if appends_in_order(parsed.entries, new_entries):
        parsed.offsets = offsets
        return parsed.extend(new_entries)
    merged = _Parsed()
    merged.offsets, merged.read = offsets, parsed.read
    return merged.extend(flatten_logs(by_writer(groups, merged.read)))


def _parse_local(files_of, app_name, verstr, files):
    fresh = _Parsed()
    fresh.offsets = {}
    return _grow(fresh, files_of, app_name, verstr, files)


def _parse_with(read_log, storage, app_name, verstr):
    return _Parsed().extend(read_log(storage, app_name, verstr))


class ParsedLogs:
    """Parsed logs per record, reused while unchanged and grown when appended.

    Bounded by *max_bytes* of log files and *max_entries* records (least
    recently used first out). A backend without cheap ``record_files`` (reads
    that merge a remote into a local copy) is never cached.
    """

    def __init__(self, max_bytes=DEFAULT_MAX_BYTES, max_entries=DEFAULT_MAX_ENTRIES):
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._entries = OrderedDict()  # key -> (_Parsed, weight)
        self._lock = threading.Lock()
        self._key_locks = {}
        self.bytes = 0

    def __len__(self):
        return len(self._entries)

    def get(self, storage, app_name, verstr, read_log):
        """The record's :class:`LogSnapshot`, reading only what changed."""
        files = _log_files(storage, app_name, verstr)
        if files is None:
            return _parse_with(read_log, storage, app_name, verstr).snapshot
        key = (_identity(storage), app_name, verstr)
        with self._key_lock(key):
            parsed = self._lookup(key)
            try:
                return self._current(key, parsed, storage, app_name, verstr, read_log, files)
            except StaleListing:  # merged since listed: list the record once more
                pass
            try:
                files = _log_files(storage, app_name, verstr)
                return self._current(key, parsed, storage, app_name, verstr, read_log, files)
            except StaleListing:
                return (parsed or _parse_with(read_log, storage, app_name, verstr)).snapshot

    def _current(self, key, parsed, storage, app_name, verstr, read_log, files):
        """The snapshot of the record listed as *files*, kept for the next poll."""
        sig = tuple(sorted(files.items()))
        if parsed is not None and parsed.sig == sig:
            return parsed.snapshot
        parsed = self._refresh(parsed, storage, app_name, verstr, read_log, files)
        if parsed is None:  # a half-written line: answer, don't keep
            return _parse_with(read_log, storage, app_name, verstr).snapshot
        parsed.sig = sig
        self._store(key, parsed, sum(s[0] for s in files.values()))
        return parsed.snapshot

    def _refresh(self, parsed, storage, app_name, verstr, read_log, files):
        direct = _direct_files(storage)
        if read_log is not load_log or direct is None:
            return _parse_with(read_log, storage, app_name, verstr)
        files_of = ListedReads(direct)
        try:
            if parsed is not None and parsed.offsets is not None:
                grown = _grow(parsed, files_of, app_name, verstr, files)
                if grown is not None:
                    return grown
            return _parse_local(files_of, app_name, verstr, files) or _parse_with(
                read_log, storage, app_name, verstr
            )
        except _Pending:
            return None

    def _key_lock(self, key):
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def _lookup(self, key):
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                return None
            self._entries.move_to_end(key)
            return hit[0]

    def _store(self, key, parsed, weight):
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self.bytes -= old[1]
            self._entries[key] = (parsed, weight)
            self.bytes += weight
            while len(self._entries) > 1 and (
                self.bytes > self._max_bytes or len(self._entries) > self._max_entries
            ):
                old_key, (_, old_weight) = self._entries.popitem(last=False)
                self.bytes -= old_weight
                self._key_locks.pop(old_key, None)


def _identity(storage):
    identity_of = getattr(storage, "cache_identity", None)
    return (identity_of() if identity_of else None) or id(storage)
