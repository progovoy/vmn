#!/usr/bin/env python3
"""Building the indexed metric file, ``metrics/<writer>.vmx`` (plan 12 §3.2).

::

    file := "VMSX" | u8 version | column chunks and LOD levels …
            | footer (JSON, zlib) | u32 footer_len | u32 crc32(footer) | "VMSX"

Each key's points are sorted on its axis (step, or timestamp for a step-less
key) and stored as raw chunks of :data:`CHUNK_POINTS` points per column, each
zlib-compressed alone, followed by its LOD levels (:mod:`metric_lod`). The
footer maps every key to its byte ranges, so a reader reads the footer from
the end and then only the slices it needs (:class:`MetricIndexReader`). A
key's summary ``first``/``last`` are its first and last write, as a block
header's are: the fold's latest value never depends on the sort. Its ``t``
is its true time bounds and its ``r``, when its steps went back, where
(:func:`~vmn_exp.core.step_restart.restart_point`). The footer's ``order``
(:data:`WRITE_ORDER`) says so; an older footer's keys are read in write order
from their columns (:mod:`~vmn_exp.core.vmx_write_order`).
"""
import json
import zlib

from vmn_exp.core.metric_columns import Columns, key_summary, pack_deltas, pack_floats, point
from vmn_exp.core.metric_index_layout import (
    CHUNK_POINTS,
    LOD_SIZES,
    MAGIC,
    TAIL,
    VERSION,
    WRITE_ORDER,
)
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.metric_lod import encode_buckets, level_buckets
from vmn_exp.core.step_restart import restart_point, with_restart

__all__ = ["CHUNK_POINTS", "LOD_SIZES", "MAGIC", "MetricIndexReader", "build_index"]


def _sorted(cols):
    axis = cols.steps if cols.has_step else cols.ts
    order = sorted(range(len(cols)), key=axis.__getitem__)
    steps = [cols.steps[i] for i in order] if cols.has_step else None
    return Columns(steps, [cols.ts[i] for i in order], [cols.values[i] for i in order])


class _Writer:
    def __init__(self):
        self.parts = [MAGIC + bytes([VERSION])]
        self.offset = len(self.parts[0])

    def put(self, data):
        entry = {"off": self.offset, "len": len(data)}
        self.parts.append(data)
        self.offset += len(data)
        return entry


def _write_column(out, cols, name, pack):
    column = getattr(cols, name)
    entries = []
    for start in range(0, len(cols), CHUNK_POINTS):
        end = min(start + CHUNK_POINTS, len(cols))
        entry = out.put(zlib.compress(pack(column[start:end])))
        entry["n"] = end - start
        entry["s"] = [cols.steps[start], cols.steps[end - 1]] if cols.has_step else None
        entry["t"] = [cols.ts[start], cols.ts[end - 1]]
        entries.append(entry)
    return entries


def _write_lod(out, cols):
    lod, finer, finer_size = {}, None, None
    for size in LOD_SIZES:
        buckets = level_buckets(cols, size, finer, finer_size)
        if len(buckets) < 2:
            break
        entry = out.put(encode_buckets(buckets))
        entry["buckets"] = len(buckets)
        lod[str(size)] = entry
        finer, finer_size = buckets, size
    return lod


def _write_ends(cols):
    """``{"first", "last"}`` points of *cols* in write order (timestamp, ties
    in logging order) — never the step ends: a writer may restart its steps."""
    positions = range(len(cols))
    first = min(positions, key=cols.ts.__getitem__)
    last = max(reversed(positions), key=cols.ts.__getitem__)
    return {"first": point(cols, first), "last": point(cols, last)}


def _write_key(out, name, cols):
    ends = _write_ends(cols)
    restart = restart_point(cols.steps)
    cols = _sorted(cols)
    summary = key_summary(name, cols)
    raw = {}
    if cols.has_step:
        raw["steps"] = _write_column(out, cols, "steps", pack_deltas)
    raw["ts"] = _write_column(out, cols, "ts", pack_deltas)
    raw["values"] = _write_column(out, cols, "values", pack_floats)
    return with_restart({
        "n": len(cols),
        "has_step": cols.has_step,
        "s": summary["s"],
        "t": [ends["first"][2], ends["last"][2]],
        "summary": {"sum": summary["sum"], **ends},
        "raw": raw,
        "lod": _write_lod(out, cols),
    }, restart)


def build_index(writer, keys, rewinds_applied=False, stream_bytes=None):
    """The bytes of an indexed file of *keys* (``{name: Columns}``, non-empty);
    *stream_bytes*: the stream prefix a live rollup built it from, which the
    footer records so its owner resumes shipping past it."""
    out = _Writer()
    footer = {
        "writer": writer,
        "format": VERSION,
        "order": WRITE_ORDER,
        "rows": sum(len(cols) for cols in keys.values()),
        "keys": {name: _write_key(out, name, cols) for name, cols in keys.items()},
        "rewinds_applied": bool(rewinds_applied),
    }
    if stream_bytes is not None:
        footer["stream_bytes"] = stream_bytes
    packed = zlib.compress(json.dumps(footer, separators=(",", ":")).encode())
    out.parts.append(packed + TAIL.pack(len(packed), zlib.crc32(packed), MAGIC))
    return b"".join(out.parts)
