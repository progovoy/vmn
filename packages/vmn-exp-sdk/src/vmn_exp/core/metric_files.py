#!/usr/bin/env python3
"""Names of a record's metric objects (plan 12 §4.2) — the one definition.

Per writer: the stream ``metrics/<writer>.vms`` and its synced segments
``metrics/<writer>@<seq>.vms`` (the log seq scheme of :mod:`logfiles`), and
once the writer finished, the indexed ``metrics/<writer>.vmx``, which
supersedes every stream object of its writer. Pure: no I/O.
"""
from vmn_exp.core.logfiles import visible_spans, writer_and_span

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


def indexed_name(writer):
    return f"{_PREFIX}{writer}{INDEXED_SUFFIX}"


def stream_writer_and_seq(name):
    """``metrics/w@000003.vms`` → ``("w", 3)``; the base stream is seq 0."""
    writer, (_, last) = writer_and_span(name, _PREFIX, STREAM_SUFFIX)
    return writer, last


def metric_writer(name):
    if is_indexed_file(name):
        return name[len(_PREFIX):-len(INDEXED_SUFFIX)]
    return stream_writer_and_seq(name)[0]


def group_metric_names(names):
    """``{writer: [names]}``: a writer's ``.vmx`` alone when there is one,
    else its stream objects in seq order."""
    streams, indexed = {}, {}
    for name in names:
        if is_indexed_file(name):
            indexed[metric_writer(name)] = name
        elif is_stream_file(name):
            writer, span = writer_and_span(name, _PREFIX, STREAM_SUFFIX)
            streams.setdefault(writer, []).append((span, name))
    groups = {w: [n for _, n in visible_spans(s)] for w, s in streams.items()}
    groups.update((w, [name]) for w, name in indexed.items())
    return groups


def group_metric_objects(sizes):
    """:func:`group_metric_names` of ``{name: size}`` as ``{writer: [(name, size)]}``."""
    return {w: [(n, sizes[n]) for n in names]
            for w, names in group_metric_names(sizes).items()}
