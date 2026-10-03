#!/usr/bin/env python3
"""Compaction (plan 12 §6): build a writer's ``metrics/<w>.vmx`` from what it
wrote, then let storage drop the stream objects (and sealed parts) it
supersedes (``put_indexed``).

Writers compact at their end (SDK finish, ``vmn-exp run`` at child exit,
importers); ``vmn-exp compact`` and ``vmn-exp watch --compact`` catch the
writers that died first. Rewinds known at build time are applied (their
points dropped); a later rewind rebuilds the file (*rebuild*). A long writer
seals a part every :data:`SEAL_POINTS` points it appends in a process, so a
live reader never decodes weeks of stream; the final ``.vmx`` merges them.
"""
import os
import tempfile
import threading

from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import is_indexed_file, is_part_file, part_writer_and_k
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.series_reader import hidden, rewind_markers, writer_source

SEAL_POINTS = 10_000_000
_SEAL_LOCK = threading.Lock()


def _objects(storage, app_name, verstr, writer):
    listing = getattr(storage, "metric_objects", None)
    return (listing(app_name, verstr) if listing else {}).get(writer, [])


def writer_columns(storage, app_name, verstr, objects, rewinds=()):
    """``{stream key: Columns}`` of one writer's *objects*, less what *rewinds* hide."""
    source = writer_source(storage, app_name, verstr, objects)
    keys = {}
    for name in source.counts():
        points = [p for p in source.points(name) if not hidden(rewinds, p[0], p[1])]
        if points:
            stepless = points[0][1] is None
            keys[name] = Columns(None if stepless else [p[1] for p in points],
                                 [p[0] for p in points], [p[2] for p in points])
    return keys


def _put(storage, app_name, verstr, writer, data, **kwargs):
    fd, path = tempfile.mkstemp(suffix=".vmx")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return bool(storage.put_indexed(app_name, verstr, writer, path, **kwargs))
    finally:
        if os.path.exists(path):
            os.unlink(path)


def is_compacted(objects):
    return any(is_indexed_file(n) for n, _ in objects)


def compact_writer(storage, app_name, verstr, writer, rewinds=(), rebuild=False):
    """Build *writer*'s ``.vmx``; True when stored. A compacted writer is
    left alone unless *rebuild*, which rewrites its file."""
    objects = _objects(storage, app_name, verstr, writer)
    if not objects or (is_compacted(objects) and not rebuild):
        return False
    keys = writer_columns(storage, app_name, verstr, objects, rewinds)
    if not keys:
        return False
    data = build_index(writer, keys, rewinds_applied=bool(rewinds))
    return _put(storage, app_name, verstr, writer, data, replace=rebuild)


def record_rewinds(storage, app_name, verstr):
    by_writer = getattr(storage, "load_logs_by_writer", None)
    logs = by_writer(app_name, verstr) if by_writer else {}
    return rewind_markers([e for entries in logs.values() for e in entries or ()])


def compact_record(storage, app_name, verstr, rebuild=False):
    """Compact every writer of the record still on streams (every writer
    with *rebuild*); the writers whose ``.vmx`` was stored, sorted."""
    listing = getattr(storage, "metric_objects", None)
    writers = sorted(listing(app_name, verstr) if listing else {})
    rewinds = record_rewinds(storage, app_name, verstr)
    return [w for w in writers
            if compact_writer(storage, app_name, verstr, w, rewinds, rebuild=rebuild)]


def seal_writer(storage, app_name, verstr, writer):
    """Seal *writer*'s stream objects as its next part; its number, or None."""
    objects = _objects(storage, app_name, verstr, writer)
    if is_compacted(objects):
        return None
    parts = [part_writer_and_k(n)[1] for n, _ in objects if is_part_file(n)]
    streams = [(n, s) for n, s in objects if not is_part_file(n)]
    keys = writer_columns(storage, app_name, verstr, streams) if streams else {}
    if not keys:
        return None
    k = max(parts, default=0) + 1
    return k if _put(storage, app_name, verstr, writer, build_index(writer, keys), part=k) else None


def note_points(storage, app_name, verstr, writer, n):
    """Count *n* points appended by *writer*; seal a part past :data:`SEAL_POINTS`."""
    with _SEAL_LOCK:
        counts = storage.__dict__.setdefault("_sealed_counts", {})
        key = (app_name, verstr, writer)
        counts[key] = counts.get(key, 0) + n
        if counts[key] < SEAL_POINTS:
            return None
        counts[key] = 0
    return seal_writer(storage, app_name, verstr, writer)
