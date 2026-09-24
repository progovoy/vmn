#!/usr/bin/env python3
"""Parsed experiment logs, kept across run-page polls.

A live run's page polls while its log grows. Re-reading the whole log each time
made a poll cost O(log); here a local record's JSONL logs are read from the
offset the last poll stopped at, and only the new entries are parsed, appended
to the series and folded into the params/metrics. The result is always what a
full parse would give — growth that could reorder the merged log (an entry
older than the newest one seen, a rewritten or shrunk file, a legacy
``log.yml``) is simply parsed again from scratch.

Entries are appended in place and each poll gets a :class:`LogSnapshot` that
sees a fixed prefix, so a slow response never observes a later poll's growth.
The cache is bounded by the log bytes it holds, not by a count of records.
"""
import threading
from collections import OrderedDict

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.cli.snapshot_storage_files import flatten_logs
from version_stamp.core.experiment_fold import fold_last_metric_at, fold_log, fold_values
from version_stamp.core.experiment_log import load_log, metric_series
from version_stamp.core.experiment_logfiles import (
    LEGACY_LOG_FILE,
    group_log_names,
    parse_json_line,
    parse_jsonl,
)

DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 128


class LogSnapshot:
    """One poll's view of a parsed log: the first ``total`` entries."""

    def __init__(self, entries, total, series, counts, fold):
        self._entries = entries
        self.total = total
        self._series = series
        self._counts = dict(counts)
        self.params = fold_values(fold, "params")
        self.metrics = fold_values(fold, "metrics")
        self.last_metric_at = fold_last_metric_at(fold)
        self.memo = {}  # derived views (thinned series) of this exact snapshot

    def log(self):
        return self._entries[: self.total]

    def tail(self, n):
        return self._entries[max(self.total - n, 0) : self.total]

    def page(self, offset, limit):
        offset = max(offset, 0)
        return self._entries[offset : min(offset + max(limit, 0), self.total)]

    def series_keys(self):
        return self._counts.keys()

    def series(self, keys=None):
        """``{metric: [points]}`` — every metric, or those of *keys* it has."""
        names = self._counts if keys is None else [k for k in keys if k in self._counts]
        return {k: self._series[k][: self._counts[k]] for k in names}


class _Parsed:
    """A record's growing parse: entries, per-metric series and the fold."""

    def __init__(self):
        self.entries, self.series, self.counts = [], {}, {}
        self.fold = fold_log([])
        self.offsets = None  # {log file: bytes consumed} when incremental
        self.sig = None
        self.snapshot = None

    def extend(self, new_entries):
        fold_log(new_entries, self.fold, start=len(self.entries))
        self.entries.extend(new_entries)
        for key, points in metric_series(new_entries).items():
            self.series.setdefault(key, []).extend(points)
            self.counts[key] = len(self.series[key])
        self.snapshot = LogSnapshot(
            self.entries, len(self.entries), self.series, self.counts, self.fold
        )
        return self


class _Pending(Exception):
    """A log ends in a complete line with no newline yet — read it fully."""


def _local(storage):
    direct = getattr(storage, "direct_files", None)
    local = direct() if direct else None
    return local if isinstance(local, LocalSnapshotStorage) else None


def _log_files(storage, app_name, verstr):
    """``{log file: signature}`` of the record, or None when unknown."""
    record_files = getattr(storage, "record_files", None)
    files = record_files(app_name, verstr) if record_files else None
    if files is None:
        return None
    return {n: tuple(sig) for n, sig in files.items() if n.startswith("log.")}


def _read_complete_lines(local, app_name, verstr, name, offset):
    """``(entries, new offset)`` from *offset* up to the last newline."""
    data = local.read_file_from(app_name, verstr, name, offset)
    if data is None:
        raise _Pending()  # vanished since listed: parse again
    cut = data.rfind(b"\n") + 1
    if parse_json_line(data[cut:].decode("utf-8", "replace")) is not None:
        raise _Pending()
    return data[:cut].decode("utf-8"), offset + cut


def _read_growth(local, app_name, verstr, files, offsets):
    """``{writer: new entries}`` and the new offsets, or None when not pure growth."""
    if any(name not in files or files[name][0] < end for name, end in offsets.items()):
        return None
    grown = [n for n in files if files[n][0] > offsets.get(n, 0)]
    new_offsets, by_writer = dict(offsets), {}
    for writer, names in group_log_names(grown).items():
        for name in names:
            text, new_offsets[name] = _read_complete_lines(
                local, app_name, verstr, name, offsets.get(name, 0)
            )
            by_writer.setdefault(writer, []).extend(parse_jsonl(text, writer))
    return by_writer, new_offsets


def _appends_in_order(entries, new_entries):
    """Whether *new_entries* all sort after *entries* in the merged log."""
    stamps = [e.get("timestamp", "") for e in new_entries]
    if not all(isinstance(ts, str) for ts in stamps):
        return False
    if not entries or not stamps:
        return True
    last = entries[-1].get("timestamp", "")
    return isinstance(last, str) and min(stamps) > last


def _grow(parsed, local, app_name, verstr, files):
    """*parsed* extended by the logs' new bytes, or None to parse afresh."""
    found = _read_growth(local, app_name, verstr, files, parsed.offsets)
    if found is None:
        return None
    by_writer, offsets = found
    new_entries = flatten_logs(by_writer)
    if not _appends_in_order(parsed.entries, new_entries):
        return None
    parsed.offsets = offsets
    return parsed.extend(new_entries)


def _parse_local(local, app_name, verstr, files):
    fresh = _Parsed()
    fresh.offsets = {}
    return _grow(fresh, local, app_name, verstr, files)


def _parse_with(read_log, storage, app_name, verstr):
    return _Parsed().extend(read_log(storage, app_name, verstr))


class ParsedLogs:
    """Parsed logs per record, reused while unchanged and grown when appended.

    Bounded by *max_bytes* of log files and *max_entries* records (least
    recently used first out). A backend without cheap ``record_files`` (reads
    that merge a remote) is never cached.
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
        local = _local(storage)
        if read_log is not load_log or local is None or LEGACY_LOG_FILE in files:
            return _parse_with(read_log, storage, app_name, verstr)
        try:
            if parsed is not None and parsed.offsets is not None:
                grown = _grow(parsed, local, app_name, verstr, files)
                if grown is not None:
                    return grown
            return _parse_local(local, app_name, verstr, files) or _parse_with(
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
