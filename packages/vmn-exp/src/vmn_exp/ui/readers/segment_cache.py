#!/usr/bin/env python3
"""A remote run's log and metric objects, read once across series requests.

A run page's joined series, Compare and outer-run charts read a run's JSONL
logs and metric objects (:func:`~vmn_exp.ui.readers.range_series.read_run`),
re-asked on every poll of a live run — whose object store holds a segment per
sync. A listed object's bytes are kept here under its listing signature (size,
LastModified, ETag), so a poll costs the record's ``log/`` and ``metrics/``
listings plus the objects that changed or appeared since; bounded by bytes,
least recently used first out. Ranged ``.vmx`` reads go to the store. An
object merged away since the listing raises
:class:`~vmn_exp.ui.readers.listed_reads.StaleListing`.
"""
import threading
from collections import OrderedDict

from vmn_exp.core.logfiles import group_log_names
from vmn_exp.core.metric_files import (
    group_metric_objects,
    is_metric_file,
    is_stream_file,
)
from vmn_exp.storage.files import parse_jsonl
from vmn_exp.ui.readers.listed_reads import ListedReads, read_each

DEFAULT_MAX_BYTES = 32 * 1024 * 1024


class SegmentCache:
    def __init__(self, max_bytes=DEFAULT_MAX_BYTES):
        self._max_bytes = max_bytes
        self._bytes = OrderedDict()  # (store, app, verstr, name, signature) -> bytes
        self._lock = threading.Lock()
        self.bytes = 0

    def holds(self, key):
        with self._lock:
            return key in self._bytes

    def read(self, key, fetch):
        """The bytes kept under *key* (its last item the listing signature),
        else ``fetch()``'s, kept when they are the listed size."""
        with self._lock:
            data = self._bytes.get(key)
            if data is not None:
                self._bytes.move_to_end(key)
                return data
        data = fetch()
        if len(data) == key[-1][0]:
            self._keep(key, data)
        return data

    def _keep(self, key, data):
        with self._lock:
            if key not in self._bytes:
                self._bytes[key] = data
                self.bytes += len(data)
            while self.bytes > self._max_bytes and len(self._bytes) > 1:
                _, old = self._bytes.popitem(last=False)
                self.bytes -= len(old)


_SEGMENTS = SegmentCache()


class SegmentReads:
    """One read of *storage*'s run: its log and metric objects listed once,
    whole objects from the cache."""

    def __init__(self, storage, cache=None):
        self._storage, self._cache = storage, cache or _SEGMENTS
        self._reads = ListedReads(storage)
        self._files = None
        self._lock = threading.Lock()

    def _listed(self, app_name, verstr):
        with self._lock:
            if self._files is None:
                self._files = self._storage.stream_files(app_name, verstr)
            return self._files

    def _key(self, app_name, verstr, name):
        sig = self._listed(app_name, verstr)[name]
        return self._storage.cache_identity(), app_name, verstr, name, sig

    def metric_objects(self, app_name, verstr):
        files = self._listed(app_name, verstr)
        return group_metric_objects({n: sig[0] for n, sig in files.items() if is_metric_file(n)})

    def read_range(self, app_name, verstr, name, offset, length):
        sig = self._listed(app_name, verstr).get(name)
        fetch = lambda: self._reads.read_range(app_name, verstr, name, offset, length)  # noqa: E731
        if offset or sig is None or sig[0] != length or not is_stream_file(name):
            return fetch()
        return self._cache.read(self._key(app_name, verstr, name), fetch)

    def load_logs_by_writer(self, app_name, verstr):
        """``{stream: entries}`` like the store's own, its objects from the cache."""
        files = self._listed(app_name, verstr)
        groups = group_log_names(files)

        def read(name):
            fetch = lambda: self._reads.read_range(app_name, verstr, name, 0, files[name][0])  # noqa: E731
            return self._cache.read(self._key(app_name, verstr, name), fetch)

        # The ones to GET first, so a stale listing is found by one of them.
        names = sorted((n for group in groups.values() for n in group),
                       key=lambda n: self._cache.holds(self._key(app_name, verstr, n)))
        bodies = dict(zip(names, read_each(read, names, "vmn-ui-segment-read")))
        return {w: [e for n in group for e in parse_jsonl(bodies[n].decode("utf-8"), w)]
                for w, group in groups.items()}


def segment_reads(storage):
    """*storage*'s run reads through the cache, when it lists signatures."""
    return SegmentReads(storage) if hasattr(storage, "stream_files") else storage
