#!/usr/bin/env python3
"""Compaction (plan 12 §6): build a stream's ``.vmx`` from what it holds,
then let storage drop the objects it covers (``put_indexed``: the segments up
to the last seq the build read — one shipped after the build stays visible).

Writers compact their stream at their end (SDK finish, ``vmn-exp run`` at
child exit, importers); ``vmn-exp compact`` and ``vmn-exp watch --compact``
catch the streams of writers that died first. Rewinds known at build time are
applied (their points dropped); a later rewind rebuilds the file (*rebuild*).
A compacted stream is never appended to again (its record copy moves on to
a new stream, ``storage.compacting``), so a long writer seals its stream —
compacts it and goes on in a new one — every :data:`SEAL_POINTS` points it
appends in a process: a live reader never decodes weeks of stream.
"""
import os
import tempfile
import threading
import time
from contextlib import nullcontext

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.index_metric_reads import MetricObjectGone
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import is_indexed_file, last_seq
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_stream import base_key, inherited_twin, is_inherited, stepless_twin
from vmn_exp.core.series_reader import hidden, rewind_markers, writer_source

SEAL_POINTS = 10_000_000
_SEAL_LOCK = threading.Lock()


def _objects(storage, app_name, verstr, writer):
    listing = getattr(storage, "metric_objects", None)
    return (listing(app_name, verstr) if listing else {}).get(writer, [])


def writer_columns(storage, app_name, verstr, objects, rewinds=()):
    """``{stream key: Columns}`` of one writer's *objects*, less what *rewinds* hide."""
    return source_columns(writer_source(storage, app_name, verstr, objects), rewinds)


def source_columns(source, rewinds=()):
    """``{stream key: Columns}`` of a series *source*, less what *rewinds* hide."""
    points = {}
    for name, ts, step, value in source.named_points():
        if not hidden(rewinds, ts, step):
            points.setdefault(name, []).append((ts, step, value))
    return {name: Columns(None if p[0][1] is None else [x[1] for x in p],
                          [x[0] for x in p], [x[2] for x in p])
            for name, p in _split_twins(points).items()}


def _twin_name(name):
    twin = stepless_twin(base_key(name))
    return inherited_twin(twin) if is_inherited(name) else twin


def _split_twins(points):
    """Move the step-less points of a key that also has stepped ones (in
    other blocks, maybe of other writer instances) to its step-less twin,
    the live writer's rule."""
    out = {}
    for name, p in points.items():
        stepped = [x for x in p if x[1] is not None]
        if stepped and len(stepped) < len(p):
            out.setdefault(_twin_name(name), []).extend(x for x in p if x[1] is None)
            p = stepped
        out.setdefault(name, []).extend(p)
    return out


def put_index(storage, app_name, verstr, writer, data, **kwargs):
    """Store the ``.vmx`` bytes *data* of stream *writer* (``put_indexed``)."""
    fd, path = tempfile.mkstemp(suffix=".vmx")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return bool(storage.put_indexed(app_name, verstr, writer, path, **kwargs))
    finally:
        if os.path.exists(path):
            os.unlink(path)


def is_compacted(objects):
    """Whether a stream's visible *objects* are all indexed (nothing to compact)."""
    return bool(objects) and all(is_indexed_file(n) for n, _ in objects)


def _compacting(storage, app_name, verstr, writer):
    hold = getattr(storage, "compacting", None)
    return hold(app_name, verstr, writer) if hold else nullcontext()


def compact_writer(storage, app_name, verstr, writer, rewinds=(), rebuild=False):
    """Build stream *writer*'s ``.vmx``; True when stored. A compacted stream
    is left alone unless *rebuild*, which rewrites its file. An object gone
    since the listing (another compactor rolled the stream up) has the
    stream listed once more; gone again, it is left to that compactor."""
    with _compacting(storage, app_name, verstr, writer):
        for _ in range(2):
            try:
                return _compact_listed(storage, app_name, verstr, writer, rewinds, rebuild)
            except MetricObjectGone:
                pass
        return False


def _compact_listed(storage, app_name, verstr, writer, rewinds, rebuild):
    objects = _objects(storage, app_name, verstr, writer)
    if not objects or (is_compacted(objects) and not rebuild):
        return False
    keys = writer_columns(storage, app_name, verstr, objects, rewinds)
    if not keys:
        return False
    data = build_index(writer, keys, rewinds_applied=bool(rewinds))
    covers = max(last_seq(n for n, _ in objects), 0)
    return put_index(storage, app_name, verstr, writer, data, replace=rebuild, covers=covers)


def record_rewinds(storage, app_name, verstr):
    by_writer = getattr(storage, "load_logs_by_writer", None)
    logs = by_writer(app_name, verstr) if by_writer else {}
    return rewind_markers([e for entries in logs.values() for e in entries or ()])


def compact_record(storage, app_name, verstr, rebuild=False):
    """Compact every stream of the record with segments past its ``.vmx``
    (every stream with *rebuild*); the streams whose ``.vmx`` was stored, sorted."""
    listing = getattr(storage, "metric_objects", None)
    objects = listing(app_name, verstr) if listing else {}
    writers = sorted(w for w, objs in objects.items() if rebuild or not is_compacted(objs))
    if not writers:
        return []  # the listing shows nothing to compact: no log is read
    rewinds = record_rewinds(storage, app_name, verstr)
    return [w for w in writers
            if compact_writer(storage, app_name, verstr, w, rewinds, rebuild=rebuild)]


def rebuild_compacted(storage, app_name, verstr):
    """Rebuild the ``.vmx`` of every compacted stream of the record, so a
    rewind appended after compaction is applied in the file."""
    listing = getattr(storage, "metric_objects", None)
    objects = listing(app_name, verstr) if listing else {}
    rewinds = record_rewinds(storage, app_name, verstr)
    return [w for w in sorted(objects) if any(is_indexed_file(n) for n, _ in objects[w])
            and compact_writer(storage, app_name, verstr, w, rewinds, rebuild=True)]


def record_compacted(storage, app_name, verstr):
    """True when every stream of the record is on a ``.vmx`` alone, False
    when one has segments, None when the record has no metric objects."""
    listing = getattr(storage, "metric_objects", None)
    objects = listing(app_name, verstr) if listing else {}
    if not objects:
        return None
    return all(is_compacted(objs) for objs in objects.values())


def _compact_quietly(storage, app_name, verstr, writer):
    try:
        compact_writer(storage, app_name, verstr, writer,
                       record_rewinds(storage, app_name, verstr))
    except Exception:
        VMN_LOGGER.debug(f"Metric compaction of {app_name} run {verstr} (stream {writer}) "
                         "failed; the stream stays", exc_info=True)


def compact_by(storage, app_name, verstr, writer, deadline):
    """Compact *writer* at its end, waiting until *deadline* (monotonic): True
    when done in time. Past it the stream stays (``vmn-exp compact`` later)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    worker = threading.Thread(target=_compact_quietly, args=(storage, app_name, verstr, writer),
                              name="vmn-metric-compact", daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        VMN_LOGGER.warning(f"vmn: {app_name} run {verstr}'s metrics stay uncompacted"
                           " (vmn-exp compact)")
        return False
    return True


def seal_writer(storage, app_name, verstr, writer):
    """Seal stream *writer*: compact it; its writer goes on in a new stream."""
    return compact_writer(storage, app_name, verstr, writer,
                          record_rewinds(storage, app_name, verstr))


def note_points(storage, app_name, verstr, writer, n):
    """Count *n* points appended to stream *writer*; seal it past :data:`SEAL_POINTS`."""
    with _SEAL_LOCK:
        counts = storage.__dict__.setdefault("_sealed_counts", {})
        key = (app_name, verstr, writer)
        counts[key] = counts.get(key, 0) + n
        if counts[key] < SEAL_POINTS:
            return None
        counts[key] = 0
    return seal_writer(storage, app_name, verstr, writer)
