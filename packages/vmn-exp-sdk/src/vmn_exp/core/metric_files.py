#!/usr/bin/env python3
"""Names of a record's metric objects (plan 12 §4.2) — the one definition.

Per stream (:mod:`vmn_exp.core.streams`): the live stream
``metrics/<stream>.vms`` and its synced segments ``metrics/<stream>@<seq>.vms``
(the log seq scheme of :mod:`logfiles`), and once compacted, the indexed
``metrics/<stream>@000000-<last>.vmx``, which supersedes the stream's
segments up to seq *last* — and nothing after it: a segment shipped after the
compaction read the stream stays visible next to it, as an object a failed
delete left behind stays hidden. Of several ``.vmx`` of a stream the one
covering most wins. Pure: no I/O.
"""
from vmn_exp.core.logfiles import writer_and_span

METRICS_DIR = "metrics"
STREAM_SUFFIX = ".vms"
INDEXED_SUFFIX = ".vmx"
_PREFIX = METRICS_DIR + "/"


def _in_dir(name):
    return name.startswith(_PREFIX) and "/" not in name[len(_PREFIX):]


def is_stream_file(name):
    return _in_dir(name) and name.endswith(STREAM_SUFFIX)


def is_indexed_file(name):
    return _in_dir(name) and name.endswith(INDEXED_SUFFIX)


def is_metric_file(name):
    return is_stream_file(name) or is_indexed_file(name)


def stream_name(writer, seq=0):
    seq_part = f"@{seq:06d}" if seq else ""
    return f"{_PREFIX}{writer}{seq_part}{STREAM_SUFFIX}"


def indexed_name(writer, last=0):
    """The ``.vmx`` of *writer*'s stream covering its segments up to *last*."""
    return f"{_PREFIX}{writer}@{0:06d}-{last:06d}{INDEXED_SUFFIX}"


def _split(name):
    suffix = INDEXED_SUFFIX if is_indexed_file(name) else STREAM_SUFFIX
    return writer_and_span(name, _PREFIX, suffix)


def stream_writer_and_seq(name):
    """``metrics/w@000003.vms`` → ``("w", 3)``; the base stream is seq 0."""
    writer, (_, last) = _split(name)
    return writer, last


def covered_seq(name):
    """The last segment seq the ``.vmx`` *name* supersedes."""
    return _split(name)[1][1]


def metric_writer(name):
    return _split(name)[0]


def last_seq(names):
    """The highest segment seq *names* (one stream's) hold or cover; -1 if none."""
    return max((stream_writer_and_seq(n)[1] for n in names), default=-1)


def group_metric_names(names):
    """``{stream: [names]}``: the stream's widest ``.vmx`` (if any), then its
    segments past what it covers, in seq order."""
    streams, indexed = {}, {}
    for name in names:
        if is_indexed_file(name):
            writer = metric_writer(name)
            if covered_seq(name) >= covered_seq(indexed.get(writer, name)):
                indexed[writer] = name
        elif is_stream_file(name):
            writer, (_, seq) = writer_and_span(name, _PREFIX, STREAM_SUFFIX)
            streams.setdefault(writer, []).append((seq, name))
    groups = {}
    for writer in set(streams) | set(indexed):
        vmx = indexed.get(writer)
        after = covered_seq(vmx) if vmx else -1
        groups[writer] = ([vmx] if vmx else []) + [
            n for seq, n in sorted(streams.get(writer, ())) if seq > after]
    return groups


def superseded(names, writer, last):
    """The objects of *writer* among *names* a ``.vmx`` covering up to *last*
    hides: its segments up to *last* and the narrower ``.vmx``."""
    hidden = []
    for name in names:
        if not is_metric_file(name) or metric_writer(name) != writer:
            continue
        if is_indexed_file(name):
            if covered_seq(name) < last:
                hidden.append(name)
        elif stream_writer_and_seq(name)[1] <= last:
            hidden.append(name)
    return hidden


def group_metric_objects(sizes):
    """:func:`group_metric_names` of ``{name: size}`` as ``{writer: [(name, size)]}``."""
    return {w: [(n, sizes[n]) for n in names]
            for w, names in group_metric_names(sizes).items()}
