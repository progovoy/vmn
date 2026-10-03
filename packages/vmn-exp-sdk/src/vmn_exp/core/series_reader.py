#!/usr/bin/env python3
"""The one way to read metric series (plan 12 §5.1): over each writer's
indexed ``.vmx`` or its ``.vms`` stream objects, plus — until ``vmn-exp
migrate`` converts them — the ``metrics`` entries of a v1 JSONL log.

Writers merge per key by ``(ts, writer)`` with each writer's own order kept:
the stable timestamp sort of the merged log (``flatten_logs``). Rewind markers
(``(step, ts_us)``, from the JSONL) hide every stepped point past their step
logged before them (§5.2). A stream key's step-less twin is merged back into
its key. Pure apart from the duck-typed storage reads of :meth:`from_storage`.
"""
import heapq

from vmn_exp.core.metric_block import decode_blocks, intact_length
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_entries import is_metric_entry, points_to_entries
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.metric_lod import emit, summarize
from vmn_exp.core.metric_stream import base_key
from vmn_exp.core.metric_time import iso_to_us, us_to_iso
from vmn_exp.core.rewind import rewind_step

LEGACY_WRITER = ""


class _StreamSource:
    """Decoded blocks of one writer's stream objects."""

    def __init__(self, blocks):
        self.blocks = blocks

    def counts(self):
        counts = {}
        for block in self.blocks:
            for name, cols in block.keys.items():
                counts[name] = counts.get(name, 0) + len(cols)
        return counts

    def points(self, name):
        for block in self.blocks:
            cols = block.keys.get(name)
            for i in range(len(cols) if cols is not None else 0):
                step = cols.steps[i] if cols.has_step else None
                yield cols.ts[i], step, cols.values[i]

    def entries(self):
        out = []
        for block in self.blocks:
            points = [(ts, step, base_key(name), value)
                      for name, cols in block.keys.items()
                      for ts, step, value in _StreamSource([block]).points(name)]
            out.extend(points_to_entries(sorted(points, key=lambda p: p[0]), block.inherited))
        return out


class _IndexedSource:
    def __init__(self, reader):
        self.reader = reader

    def counts(self):
        return {k: meta["n"] for k, meta in self.reader.footer["keys"].items()}

    def points(self, name):
        for p in self.reader.points(name):
            yield p["ts"], p["step"], p["value"]

    def entries(self):
        points = [(ts, step, base_key(name), value)
                  for name in self.reader.keys() for ts, step, value in self.points(name)]
        return points_to_entries(sorted(points, key=lambda p: p[0]))


class _EntrySource:
    """The ``metrics`` entries of a v1 log (already rewind-filtered)."""

    def __init__(self, entries):
        self._entries = [e for e in entries if is_metric_entry(e)]

    def counts(self):
        counts = {}
        for entry in self._entries:
            for key in entry.get("values") or {}:
                counts[key] = counts.get(key, 0) + 1
        return counts

    def points(self, name):
        for entry in self._entries:
            values = entry.get("values") or {}
            if name in values:
                yield iso_to_us(entry.get("timestamp")) or 0, entry.get("step"), values[name]

    def entries(self):
        return list(self._entries)


def stream_entries(data):
    """``(metrics entries, bytes used)`` of the intact blocks of stream bytes
    *data* — the log view of a stream's growth."""
    end = intact_length(data)
    return _StreamSource(list(decode_blocks(data[:end]))).entries(), end


def rewind_markers(log):
    """``[(step, ts_us)]`` of the rewind entries of *log*."""
    markers = []
    for entry in log or ():
        step = rewind_step(entry) if isinstance(entry, dict) else None
        if step is not None:
            markers.append((step, iso_to_us(entry.get("timestamp")) or 0))
    return markers


def _hidden(rewinds, ts, step):
    return step is not None and any(r_step < step and ts < r_ts for r_step, r_ts in rewinds)


def _stream_blocks(storage, app_name, verstr, objects):
    blocks = []
    for name, size in objects:
        data = storage.read_range(app_name, verstr, name, 0, size)
        blocks.extend(decode_blocks(data or b""))
    return blocks


def _source(storage, app_name, verstr, objects):
    if len(objects) == 1 and is_indexed_file(objects[0][0]):
        name, size = objects[0]
        read = lambda off, n: storage.read_range(app_name, verstr, name, off, n)  # noqa: E731
        return _IndexedSource(MetricIndexReader(read, size))
    return _StreamSource(_stream_blocks(storage, app_name, verstr, objects))


class SeriesReader:
    def __init__(self, sources, rewinds=()):
        """*sources*: ``[(writer, source)]``; merged in writer order."""
        self._sources = sorted(sources, key=lambda s: s[0])
        self._rewinds = list(rewinds)
        self._names = None

    @classmethod
    def from_storage(cls, storage, app_name, verstr, log=None, rewinds=None, legacy=None):
        """The record's metric objects; rewinds from *log* unless given.
        *legacy* are v1 ``metrics`` entries to read along."""
        listing = getattr(storage, "metric_objects", None)
        objects = listing(app_name, verstr) if listing else {}
        sources = [(w, _source(storage, app_name, verstr, objs)) for w, objs in objects.items()]
        if legacy:
            sources.append((LEGACY_WRITER, _EntrySource(legacy)))
        return cls(sources, rewind_markers(log) if rewinds is None else rewinds)

    @classmethod
    def from_entries(cls, entries):
        return cls([(LEGACY_WRITER, _EntrySource(entries))])

    def _raw_names(self):
        """``{key: [(rank, source, raw name, count)]}``."""
        if self._names is None:
            self._names = {}
            for rank, (_, source) in enumerate(self._sources):
                for name, n in source.counts().items():
                    self._names.setdefault(base_key(name), []).append((rank, source, name, n))
        return self._names

    def keys(self):
        """``{key: number of points}``; counts read no values unless a rewind
        may hide some."""
        if not self._rewinds:
            return {k: sum(r[3] for r in raws) for k, raws in self._raw_names().items()}
        counts = {k: len(self._merged(k)) for k in self._raw_names()}
        return {k: n for k, n in counts.items() if n}

    def _merged(self, key):
        """``[(ts, rank, step, value)]`` of *key* in series order."""
        per_rank = {}
        for rank, source, name, _ in self._raw_names().get(key, ()):
            per_rank.setdefault(rank, []).extend(
                (ts, rank, step, value) for ts, step, value in source.points(name)
                if not _hidden(self._rewinds, ts, step))
        lists = [sorted(points, key=lambda p: p[0]) for points in per_rank.values()]
        return list(heapq.merge(*lists, key=lambda p: (p[0], p[1])))

    def points(self, key, step_range=None, ts_range=None):
        """*key*'s :class:`Columns` (a step-less point's step is None)."""
        kept = [p for p in self._merged(key)
                if _within(p[2], step_range) and _within(p[0], ts_range)]
        return Columns([p[2] for p in kept], [p[0] for p in kept], [p[3] for p in kept])

    def columns(self, key):
        return self.points(key)

    def series(self, key, step_range=None):
        """``[{"step", "ts": iso, "value"}]`` of *key*."""
        cols = self.points(key, step_range)
        return [{"step": s, "ts": us_to_iso(t), "value": v}
                for s, t, v in zip(cols.steps, cols.ts, cols.values)]

    def thinned(self, key, max_points, step_range=None):
        """At most about *max_points* min/max-thinned points, first and last kept."""
        cols = self.points(key, step_range)
        max_points = max(int(max_points), 2)
        if len(cols) <= max_points:
            return self.series(key, step_range)
        n_buckets, size = (max_points - 2) // 2, 1
        while n_buckets and -(-(len(cols) - 2) // size) > n_buckets:
            size *= 2
        kept = [_point(cols, 0)]
        for start in range(1, len(cols) - 1, size) if n_buckets else ():
            kept += [_iso(p) for p in emit(summarize(_stepped(cols), start,
                                                      min(start + size, len(cols) - 1)))]
        return kept + [_point(cols, len(cols) - 1)]

    def entries_by_writer(self):
        """``{writer: metrics entries}`` for log views (rewinds not applied)."""
        return {writer: source.entries() for writer, source in self._sources}


def _within(value, bounds):
    if bounds is None:
        return True
    lo, hi = bounds
    if value is None:
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _stepped(cols):
    if all(s is not None for s in cols.steps):
        return cols
    return Columns(None, cols.ts, cols.values)


def _point(cols, i):
    return {"step": cols.steps[i], "ts": us_to_iso(cols.ts[i]), "value": cols.values[i]}


def _iso(point):
    return dict(point, ts=us_to_iso(point["ts"]))
