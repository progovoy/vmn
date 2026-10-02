#!/usr/bin/env python3
"""Building the indexed metric file, ``metrics/<writer>.vmx`` (plan 12 §3.2).

::

    file := "VMSX" | u8 version | column chunks and LOD levels …
            | footer (JSON, zlib) | u32 footer_len | u32 crc32(footer) | "VMSX"

Each key's points are sorted on its axis (step, or timestamp for a step-less
key) and stored as raw chunks of :data:`CHUNK_POINTS` points per column, each
zlib-compressed alone, followed by its LOD levels (:mod:`metric_lod`). The
footer maps every key to its byte ranges, so a reader reads the footer from
the end and then only the slices it needs (:class:`MetricIndexReader`).
"""
import json
import zlib

from vmn_exp.core.metric_columns import Columns, key_summary, pack_deltas, pack_floats
from vmn_exp.core.metric_index_layout import CHUNK_POINTS, LOD_SIZES, MAGIC, VERSION, TAIL
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.metric_lod import encode_buckets, level_buckets

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


def _write_key(out, name, cols):
    cols = _sorted(cols)
    summary = key_summary(name, cols)
    raw = {}
    if cols.has_step:
        raw["steps"] = _write_column(out, cols, "steps", pack_deltas)
    raw["ts"] = _write_column(out, cols, "ts", pack_deltas)
    raw["values"] = _write_column(out, cols, "values", pack_floats)
    return {
        "n": len(cols),
        "has_step": cols.has_step,
        "s": summary["s"],
        "t": summary["t"],
        "summary": {k: summary[k] for k in ("sum", "first", "last")},
        "raw": raw,
        "lod": _write_lod(out, cols),
    }


def build_index(writer, keys, rewinds_applied=False):
    """The bytes of an indexed file of *keys* (``{name: Columns}``, non-empty)."""
    out = _Writer()
    footer = {
        "writer": writer,
        "format": VERSION,
        "rows": sum(len(cols) for cols in keys.values()),
        "keys": {name: _write_key(out, name, cols) for name, cols in keys.items()},
        "rewinds_applied": bool(rewinds_applied),
    }
    packed = zlib.compress(json.dumps(footer, separators=(",", ":")).encode())
    out.parts.append(packed + TAIL.pack(len(packed), zlib.crc32(packed), MAGIC))
    return b"".join(out.parts)
