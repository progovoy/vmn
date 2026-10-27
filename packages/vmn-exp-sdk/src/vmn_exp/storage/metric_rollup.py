#!/usr/bin/env python3
"""A live metric stream's rollup (plan 12 §6): what its owner shipped, as a
``.vmx`` covering the segments up to some seq — the last few left listed
after it — so a reader of a long-lived run lists and GETs one ``.vmx`` and a
few segments, not a segment per sync.

The remote's segments are consecutive slices of the owner's local stream,
so the ``.vmx`` is built from the local file's prefix they hold, outside the
copy's ship lock (:mod:`cached_metrics` puts it under the lock). It covers
the stream's segments only up to its seq: the stream goes on (it is not
retired, unlike a compaction), shipping past it, and its footer records the
prefix length (``stream_bytes``), from which the owner resumes when its ship
state is lost. The rollup is never applied to rewinds: readers apply them,
as to a stream.
"""
from vmn_exp.core.metric_block import decode_blocks, intact_length
from vmn_exp.core.metric_compact import put_index, source_columns
from vmn_exp.core.metric_files import is_indexed_file, last_seq, stream_name
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.series_reader import blocks_source


def plan(objects, stream, seq, shipped, lag):
    """``(covers, prefix bytes)`` of the rollup after segment *seq* of
    *stream* shipped (the remote then holding its first *shipped* bytes):
    the segments up to ``seq - lag``, which hold the prefix; None unless the
    remote's *objects* (``[(name, size)]`` of the stream) list each one past it."""
    covers, sizes = seq - lag, dict(objects)
    later = [stream_name(stream, s) for s in range(covers + 1, seq + 1)]
    if any(n not in sizes for n in later):
        return None
    return covers, shipped - sum(sizes[n] for n in later)


def build(data, stream):
    """The ``.vmx`` bytes of the stream prefix *data*; None when it does not
    end on a block, or holds no point."""
    if not data or intact_length(data) != len(data):
        return None
    keys = source_columns(blocks_source(list(decode_blocks(data))))
    return build_index(stream, keys, stream_bytes=len(data)) if keys else None


def put(remote, app_name, verstr, stream, data, covers):
    """Put the rollup *data* covering the segments up to *covers*."""
    return put_index(remote, app_name, verstr, stream, data, replace=False, covers=covers)


def resumed_state(remote, app_name, verstr, objects):
    """``(bytes, next seq)`` the remote holds of a rolled-up stream
    (*objects*: its ``.vmx``, then its segments), None for any other ``.vmx``."""
    if not objects or not is_indexed_file(objects[0][0]):
        return None
    name, size = objects[0]
    read = lambda off, n: remote.read_range(app_name, verstr, name, off, n)  # noqa: E731
    held = MetricIndexReader(read, size).footer.get("stream_bytes")
    if held is None:
        return None
    return held + sum(s for _, s in objects[1:]), last_seq(n for n, _ in objects) + 1
