#!/usr/bin/env python3
"""A ``.vmx`` taking the place of metric segments the index already folded
(plan 12 §5.3): the stream's compaction, or its owner's live rollup — which
leaves its last few segments, maybe folded too, listed after it.

The ``.vmx`` holds just the points folded from what it supersedes when its
footer's per-key counts are the writer's sums (:mod:`fold_sums`) less the
points of the folded segments past it. Those come from the writer's *tail*:
the per-key counts of its :data:`TAIL_SEGMENTS` latest folded segments, kept
in the record state next to the sums. Then the ``.vmx`` replaces those
objects in the state for one footer read and nothing is folded; else the
caller refolds the record.
"""
from vmn_exp.core.fold_blocks import footer_entries
from vmn_exp.core.fold_sums import counts
from vmn_exp.core.metric_files import (
    covered_seq,
    is_indexed_file,
    metric_writer,
    stream_writer_and_seq,
    superseded,
)
from vmn_exp.core.metric_index_reader import MetricIndexReader

# At least the segments a live rollup leaves after it (cached_metrics' LIVE_ROLLUP_LAG).
TAIL_SEGMENTS = 8


def note_tail(state, writer, name, added):
    """Count the points per key (*added*) folded from stream object *name*
    into *writer*'s tail, which keeps its latest :data:`TAIL_SEGMENTS`."""
    if writer not in state.get("sums", {}) or not added:
        return
    tail = state.setdefault("tails", {}).setdefault(writer, {})
    held = tail.setdefault(name, {})
    for key, n in added.items():
        held[key] = held.get(key, 0) + n
    for old in sorted(tail, key=_seq)[:-TAIL_SEGMENTS]:
        del tail[old]


def adopted(state, storage, where, writer, vmx):
    """Whether *writer*'s new ``.vmx`` (*vmx*: name, size) holds just the
    points folded from the objects it supersedes; if so it takes their place
    in *state*."""
    name, size = vmx
    sums = state.get("sums", {}).get(writer)
    last = covered_seq(name)
    covered = superseded(state["objects"], writer, last)
    tail = state.get("tails", {}).get(writer, {})
    after = [n for n in state["objects"]
             if metric_writer(n) == writer and n not in covered]
    if sums is None or _seqs(covered) != set(range(last + 1)) or any(n not in tail for n in after):
        return False
    expected = counts(sums)
    for n in after:
        for key, points in tail[n].items():
            expected[key] -= points
    read = lambda off, n: storage.read_range(*where, name, off, n)  # noqa: E731
    footer = MetricIndexReader(read, size).footer
    if {e["k"]: e["n"] for e in footer_entries(footer)} != {k: n for k, n in expected.items() if n}:
        return False
    for n in covered:
        del state["objects"][n]
        tail.pop(n, None)
    state["objects"][name] = size
    return True


def _seq(name):
    return stream_writer_and_seq(name)[1]


def _seqs(names):
    """The segment seqs *names* (one writer's) hold or cover."""
    seqs = set()
    for name in names:
        seqs.update(range(covered_seq(name) + 1) if is_indexed_file(name) else [_seq(name)])
    return seqs
