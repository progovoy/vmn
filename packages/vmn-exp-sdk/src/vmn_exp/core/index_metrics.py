#!/usr/bin/env python3
"""Keep one experiment's fold current with its metric streams (plan 12 §5.3).

Like the JSONL logs (:mod:`index_logs`), a writer's ``.vms`` objects only
grow at the end, so a grown stream costs its new blocks' **headers**: the
prefix carries the header length, the body is never read (unless a known
rewind may hide some of the block's points). A ``.vmx`` is folded from its
footer. Anything but growth — an object gone or shrunk, a ``.vmx``
replacing segments already folded, a ``.vmx`` rewritten at another size —
asks the caller to refold the record.
"""
from vmn_exp.core.fold_blocks import (
    apply_block_points,
    apply_header,
    block_points,
    footer_entries,
    may_be_rewound,
)
from vmn_exp.core.metric_block import Block, decode_blocks, header_at
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import (
    is_indexed_file,
    is_metric_file,
    metric_writer,
    stream_writer_and_seq,
)
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.series_reader import read_concurrently


def metric_signatures(names):
    """``{name: signature}`` of the metric files among the listed *names*."""
    return {n: list(sig) for n, sig in names.items() if is_metric_file(n)}


def _new_state(sigs=None):
    return {"sig": dict(sigs or {}), "objects": {}, "points": {}}


def metric_state_sigs(record):
    return (record.get("metrics") or {}).get("sig", {})


def update_metrics(record, storage, where, sigs):
    """Fold *record*'s metric objects' growth; None when *sigs* show no
    change, False when the record must be refolded."""
    state = record.setdefault("metrics", _new_state())
    if state["sig"] == sigs:
        return None
    state["sig"] = dict(sigs)
    return _fold_growth(record["fold"], state, storage, where)


def refold_metrics(record, storage, where):
    """Fold every metric object into *record*'s (fresh) fold."""
    record["metrics"] = state = _new_state(metric_state_sigs(record))
    _fold_growth(record["fold"], state, storage, where)


def _objects(storage, where):
    listing = getattr(storage, "metric_objects", None)
    return listing(*where) if listing else {}


def _grew_only(state, objects):
    sizes = {name: size for objs in objects.values() for name, size in objs}
    for name, consumed in state["objects"].items():
        if sizes.get(name, -1) < consumed or (is_indexed_file(name) and sizes[name] != consumed):
            return False
        if not is_indexed_file(name) and _newly_indexed(state, objects, metric_writer(name)):
            return False
    return True


def _newly_indexed(state, objects, writer):
    """Whether a ``.vmx`` not yet folded replaced *writer*'s segments."""
    return any(is_indexed_file(n) and n not in state["objects"]
               for n, _ in objects.get(writer, ()))


def _fold_growth(fold, state, storage, where):
    objects = _objects(storage, where)
    if not _grew_only(state, objects):
        return False
    todo = [(writer, name, size) for writer in sorted(objects)
            for name, size in objects[writer] if state["objects"].get(name, 0) < size]
    readers = read_concurrently(lambda item: _reader(state, storage, where, *item[1:]), todo)
    for (writer, name, size), reader in zip(todo, readers):
        _fold_object(fold, state, writer, name, size, reader)
    return True


def _reader(state, storage, where, name, size):
    """What folds *name*'s unread part: its :class:`MetricIndexReader`, else
    ``read(offset, length)`` — over a synced segment's bytes read whole (one
    GET instead of two per block; a live stream grows, its body unread)."""
    read = lambda off, n: storage.read_range(*where, name, off, n)  # noqa: E731
    if is_indexed_file(name):
        return MetricIndexReader(read, size)
    consumed = state["objects"].get(name, 0)
    if not stream_writer_and_seq(name)[1]:
        return read
    data = read(consumed, size - consumed) or b""
    return lambda off, n: data[off - consumed:off - consumed + n]


def _fold_object(fold, state, writer, name, size, reader):
    if is_indexed_file(name):
        _fold_indexed(fold, state, writer, reader)
        state["objects"][name] = size
        return
    consumed = state["objects"].get(name, 0)
    while True:
        found = header_at(reader, consumed, size)
        if found is None:
            break
        header, length = found
        start = consumed
        _fold_block(fold, state, writer, header,
                    lambda: decode_blocks(reader(start, length) or b""))
        consumed += length
    state["objects"][name] = consumed


def _fold_block(fold, state, writer, header, decoded):
    """Fold one block from its *header*, or point by point from *decoded()*
    (its :class:`Block` s) when a known rewind may hide some of them."""
    base = state["points"].get(writer, 0)
    if may_be_rewound(fold, header):
        for block in decoded():
            apply_block_points(fold, writer, base, block)
    else:
        apply_header(fold, writer, base, header)
    state["points"][writer] = base + block_points(header)


def _fold_indexed(fold, state, writer, reader):
    header = {"keys": footer_entries(reader.footer)}
    keys = lambda: {k: _columns(reader, k) for k in reader.keys()}  # noqa: E731
    _fold_block(fold, state, writer, header, lambda: [Block(header, keys())])


def _columns(reader, key):
    points = reader.points(key)
    steps = [p["step"] for p in points]
    return Columns(None if steps and steps[0] is None else steps,
                   [p["ts"] for p in points], [p["value"] for p in points])
