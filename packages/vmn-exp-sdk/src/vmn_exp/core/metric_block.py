#!/usr/bin/env python3
"""Blocks of a metric stream, ``metrics/<writer>.vms`` (plan 12 §3.1).

::

    block := "VMSB" | u8 version | u32 header_len | u32 body_len
             | u32 crc32(header + body) | header (JSON) | body (zlib)

The header carries per-key summaries, so a fold reads headers only
(:func:`read_headers`); the body holds each key's delta int64 steps (absent
for step-less keys), delta int64 ``ts_us`` and float64 values. A torn or
CRC-bad tail ends the stream silently, like a torn last JSONL line.
"""
import json
import struct
import zlib
from dataclasses import dataclass

from vmn_exp.core.metric_columns import (
    Columns,
    key_summary,
    pack_deltas,
    pack_floats,
    unpack_deltas,
    unpack_floats,
)

MAGIC = b"VMSB"
VERSION = 1
_PREFIX = struct.Struct("<4sBIII")


@dataclass
class Block:
    header: dict
    keys: dict

    @property
    def inherited(self):
        return bool(self.header.get("inherited"))


def encode_block(keys, inherited=False):
    """One block of *keys* (``{name: Columns}``, each non-empty)."""
    header = {
        "keys": [key_summary(name, cols) for name, cols in keys.items()],
        "inherited": bool(inherited),
    }
    body = b"".join(_pack_key(cols) for cols in keys.values())
    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    body_bytes = zlib.compress(body)
    crc = zlib.crc32(header_bytes + body_bytes)
    prefix = _PREFIX.pack(MAGIC, VERSION, len(header_bytes), len(body_bytes), crc)
    return prefix + header_bytes + body_bytes


def _pack_key(cols):
    steps = pack_deltas(cols.steps) if cols.has_step else b""
    return steps + pack_deltas(cols.ts) + pack_floats(cols.values)


def _frames(source):
    """``(offset, header_bytes, body_bytes)`` of every intact block."""
    read = source.read if hasattr(source, "read") else _bytes_reader(source)
    offset = 0
    while True:
        prefix = read(_PREFIX.size)
        if len(prefix) < _PREFIX.size:
            return
        magic, version, header_len, body_len, crc = _PREFIX.unpack(prefix)
        if magic != MAGIC or version != VERSION:
            return
        header = read(header_len)
        body = read(body_len)
        if len(header) < header_len or len(body) < body_len:
            return
        if zlib.crc32(header + body) != crc:
            return
        yield offset, header, body
        offset += _PREFIX.size + header_len + body_len


def _bytes_reader(data):
    view = memoryview(data)
    pos = 0

    def read(n):
        nonlocal pos
        chunk = bytes(view[pos : pos + n])
        pos += len(chunk)
        return chunk

    return read


def read_headers(source):
    """The JSON header of every intact block; bodies are not decompressed."""
    for _, header, _ in _frames(source):
        yield json.loads(header)


def decode_blocks(source):
    """Every intact :class:`Block` of *source* (bytes or a binary file)."""
    for _, header, body in _frames(source):
        parsed = json.loads(header)
        yield Block(parsed, _unpack_keys(parsed["keys"], zlib.decompress(body)))


def intact_length(source):
    """Bytes of *source* up to the end of its last intact block — where a
    writer truncates a torn tail before appending."""
    end = 0
    for offset, header, body in _frames(source):
        end = offset + _PREFIX.size + len(header) + len(body)
    return end


def _unpack_keys(entries, body):
    keys, pos = {}, 0

    def take(width):
        nonlocal pos
        chunk = body[pos : pos + width]
        pos += width
        return chunk

    for entry in entries:
        n = entry["n"]
        steps = unpack_deltas(take(8 * n)) if entry["has_step"] else None
        ts = unpack_deltas(take(8 * n))
        keys[entry["k"]] = Columns(steps, ts, unpack_floats(take(8 * n)))
    return keys
