#!/usr/bin/env python3
"""Range reads of an indexed metric file (plan 12 §3.2).

The reader only needs ``read_range(offset, length)`` — a local ``pread`` or
an object-store range GET. It reads the last :data:`TAIL_READ_BYTES` of the
file once — the footer, and the whole of a file that small, which then needs
no other read; a later read inside it costs none either — then for a query
the raw chunks or the one LOD slice the answer needs, the chunks one query
lacks read concurrently, adjacent ones (a key's steps, timestamps and values)
in one read. Queries may run on several threads at once.
"""
import bisect
import json
import threading
import zlib
from collections import OrderedDict

from vmn_exp.core.metric_columns import Columns, unpack_deltas, unpack_floats
from vmn_exp.core.metric_index_layout import CHUNK_POINTS, MAGIC, TAIL
from vmn_exp.core.metric_lod import decode_buckets, emit, merge, summarize
from vmn_exp.storage.fanout import fan_out

_CACHED_CHUNKS = 16
# What the first read takes from the end of the file: on an object store one
# round trip holds the footer, or the whole file.
TAIL_READ_BYTES = 64 * 1024
_UNPACK = {"steps": unpack_deltas, "ts": unpack_deltas, "values": unpack_floats}


class MetricIndexReader:
    def __init__(self, read_range, size):
        tail_at = max(size - TAIL_READ_BYTES, 0)
        tail = read_range(tail_at, size - tail_at)
        self._read = _in_memory(tail) if tail_at == 0 else _tail_first(read_range, tail, tail_at)
        self._buffered = tail_at == 0
        footer_len, crc, magic = TAIL.unpack(tail[-TAIL.size:])
        if magic != MAGIC:
            raise ValueError("not an indexed metric file")
        start = size - TAIL.size - footer_len
        if start >= tail_at:
            packed = tail[start - tail_at:start - tail_at + footer_len]
        else:
            packed = read_range(start, footer_len)
        if zlib.crc32(packed) != crc:
            raise ValueError("indexed metric file footer is corrupt")
        self.footer = json.loads(zlib.decompress(packed))
        self._chunks = OrderedDict()
        self._lock = threading.Lock()

    def keys(self):
        return list(self.footer["keys"])

    def points(self, key, lo=None, hi=None):
        """Raw points of *key* with ``lo <= axis <= hi`` (the axis is the
        step, or the timestamp for a step-less key)."""
        meta = self.footer["keys"][key]
        p0, p1 = self._bounds(meta, lo, hi)
        return _as_points(self._columns(meta, p0, p1 + 1))

    def series(self, key, max_points, lo=None, hi=None, level=None):
        """At most about *max_points* min/max-thinned points of the range,
        its first and last points kept; *level* forces a LOD bucket size."""
        meta = self.footer["keys"][key]
        p0, p1 = self._bounds(meta, lo, hi)
        max_points = max(int(max_points), 2)
        if level is None:
            if p1 - p0 + 1 <= max_points:
                return _as_points(self._columns(meta, p0, p1 + 1))
            level = _pick_level(meta, p0, p1, max_points)
        if level is None:
            return self._thin_raw(meta, p0, p1, max_points)
        return self._thin_lod(meta, int(level), p0, p1, max_points)

    def _bounds(self, meta, lo, hi):
        """Inclusive positions of the range; ``p0 > p1`` when it is empty."""
        axis = "steps" if meta["has_step"] else "ts"
        chunks = meta["raw"][axis]
        p0 = 0 if lo is None else self._locate(meta, axis, chunks, lo, bisect.bisect_left)
        p1 = meta["n"] - 1
        if hi is not None:
            p1 = self._locate(meta, axis, chunks, hi, bisect.bisect_right) - 1
        return p0, p1

    def _locate(self, meta, axis, chunks, bound, search):
        """The position *search* gives for *bound* over the whole axis."""
        side = 1 if search is bisect.bisect_left else 0
        bound_key = "s" if axis == "steps" else "t"
        firsts = [c[bound_key][side] for c in chunks]
        index = (bisect.bisect_left if side else bisect.bisect_right)(firsts, bound)
        index = index if side else index - 1
        if index < 0:
            return 0
        if index >= len(chunks):
            return meta["n"]
        return index * CHUNK_POINTS + search(self._chunk(chunks, axis, index), bound)

    def _chunk(self, chunks, column, index, data=None):
        """Chunk *index* of a key's *column*, unpacked from *data* when read
        already."""
        entry = chunks[index]
        cache_key = (entry["off"], column)
        with self._lock:
            cached = self._chunks.get(cache_key)
            if cached is not None:
                self._chunks.move_to_end(cache_key)
                return cached
        if data is None:
            data = self._read(entry["off"], entry["len"])
        values = _UNPACK[column](zlib.decompress(data))
        with self._lock:
            self._chunks[cache_key] = values
            if len(self._chunks) > _CACHED_CHUNKS:
                self._chunks.popitem(last=False)
        return values

    def _column(self, meta, column, start, end):
        if column not in meta["raw"]:
            return None
        chunks, out = meta["raw"][column], []
        for index in _chunk_span(start, end):
            base = index * CHUNK_POINTS
            out.extend(self._chunk(chunks, column, index)[max(start - base, 0) : end - base])
        return out

    def _prefetch(self, meta, start, end):
        """Read the chunks of ``[start, end)`` not cached yet, concurrently."""
        if self._buffered:
            return
        wanted = [(meta["raw"][column], column, index)
                  for column in _UNPACK if column in meta["raw"]
                  for index in _chunk_span(start, end)]
        with self._lock:
            wanted = [w for w in wanted
                      if (w[0][w[2]]["off"], w[1]) not in self._chunks]
        if len(wanted) < 2 or len(wanted) > _CACHED_CHUNKS:
            return
        runs = _adjacent(wanted)
        fan_out(self._read_run, runs, len(runs), "vmn-metric-chunks")

    def _read_run(self, run):
        """Read a run of adjacent chunks (``[(offset, wanted)]``) at once."""
        start = run[0][0]
        last_chunks, _, last_index = run[-1][1]
        data = self._read(start, run[-1][0] + last_chunks[last_index]["len"] - start)
        for off, (chunks, column, index) in run:
            self._chunk(chunks, column, index, data[off - start:off - start + chunks[index]["len"]])

    def _columns(self, meta, start, end):
        """Positions ``[start, end)`` of *meta*'s key as :class:`Columns`."""
        if end <= start:
            return Columns(None if not meta["has_step"] else [], [], [])
        self._prefetch(meta, start, end)
        read = lambda column: self._column(meta, column, start, end)  # noqa: E731
        return Columns(read("steps"), read("ts"), read("values"))

    def _edge(self, meta, start, end):
        cols = self._columns(meta, start, end)
        return emit(summarize(cols, 0, len(cols))) if len(cols) else []

    def _thin_lod(self, meta, size, p0, p1, max_points):
        k0, k1 = _bucket_span(size, p0, p1)
        entry = meta["lod"][str(size)]
        buckets = []
        if k1 >= k0:
            raw = self._read(entry["off"] + k0 * 64, (k1 - k0 + 1) * 64)
            buckets = _merge_to(decode_buckets(raw), (max_points - 2) // 2)
        else:
            k0 = k1 = (p1 - 1) // size  # no full bucket: a single raw edge
        kept = self._edge(meta, p0, p0 + 1)
        kept += self._edge(meta, p0 + 1, max(1 + k0 * size, p0 + 1))
        for bucket in buckets:
            kept += emit(bucket)
        kept += self._edge(meta, max(1 + (k1 + 1) * size, p0 + 1), p1)
        if p1 > p0:
            kept += self._edge(meta, p1, p1 + 1)
        return kept

    def _thin_raw(self, meta, p0, p1, max_points):
        cols = self._columns(meta, p0, p1 + 1)
        n_buckets, size = (max_points - 2) // 2, 1
        while n_buckets and -(-(len(cols) - 2) // size) > n_buckets:
            size *= 2
        kept = [_point(cols, 0)]
        for start in range(1, len(cols) - 1, size) if n_buckets else ():
            kept += emit(summarize(cols, start, min(start + size, len(cols) - 1)))
        return kept + [_point(cols, len(cols) - 1)]


def _in_memory(data):
    return lambda offset, length: data[offset:offset + length]


def _tail_first(read_range, tail, tail_at):
    """*read_range*, but a read inside the *tail* read at *tail_at* is a slice."""
    def read(offset, length):
        if offset >= tail_at:
            return tail[offset - tail_at:offset - tail_at + length]
        return read_range(offset, length)
    return read


def _adjacent(wanted):
    """*wanted* chunks (``(chunks, column, index)``) as runs of adjacent
    ones, ``[(offset, wanted)]`` each, in file order."""
    runs, end = [], None
    for item in sorted(wanted, key=lambda w: w[0][w[2]]["off"]):
        entry = item[0][item[2]]
        if entry["off"] != end:
            runs.append([])
        runs[-1].append((entry["off"], item))
        end = entry["off"] + entry["len"]
    return runs


def _chunk_span(start, end):
    return range(start // CHUNK_POINTS, -(-end // CHUNK_POINTS))


def _bucket_span(size, p0, p1):
    """First and last full bucket inside the interior ``(p0, p1)``."""
    return -(-p0 // size), (p1 - 1) // size - 1


def _pick_level(meta, p0, p1, max_points):
    """The coarsest LOD level with at least ``max_points / 2`` buckets in range."""
    best = None
    for size in sorted(int(s) for s in meta["lod"]):
        k0, k1 = _bucket_span(size, p0, p1)
        if k1 - k0 + 1 >= max_points / 2:
            best = size
    return best


def _merge_to(buckets, limit):
    """Merge adjacent buckets pairwise until at most *limit* remain."""
    while limit and len(buckets) > limit:
        pairs = [merge(a, b) for a, b in zip(buckets[::2], buckets[1::2])]
        buckets = pairs + buckets[len(pairs) * 2 :]
    return buckets


def _point(cols, i):
    step = cols.steps[i] if cols.steps is not None else None
    return {"step": step, "value": cols.values[i], "ts": cols.ts[i]}


def _as_points(cols):
    return [_point(cols, i) for i in range(len(cols))]
