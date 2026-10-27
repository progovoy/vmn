#!/usr/bin/env python3
"""Keep one experiment's fold current with its metric streams (plan 12 §5.3).

Like the JSONL logs (:mod:`index_logs`), a writer's ``.vms`` objects only
grow at the end, so a grown stream costs its new blocks' **headers**: the
prefix carries the header length, the body is never read (unless a known
rewind may hide some of the block's points). A ``.vmx`` is folded from its
footer. A synced segment never grows, so it is read whole in one GET, as is
a remote store's base segment.

The record state keeps, per writer folded from its first point on, what its
points add up to (:mod:`~vmn_exp.core.fold_sums`): a ``.vmx`` replacing
segments already folded takes their place for its footer read
(:mod:`~vmn_exp.core.index_metric_adopt`), and a refold of the record (its
log rolled up or compacted) folds those sums again instead of reading the
writer's objects, unless a rewind may hide some of their points. Anything
else — an object gone or shrunk, a ``.vmx`` holding points not folded, one
rewritten at another size — asks the caller to refold the record. A writer down to its ``.vmx`` alone keeps no sums (its
refold is a footer read).
"""
from vmn_exp.core.fold_blocks import (
    apply_block_points,
    apply_header,
    apply_sums,
    block_points,
    footer_entries,
    may_be_rewound,
)
from vmn_exp.core.fold_sums import add_block
from vmn_exp.core.index_metric_adopt import adopted, note_tail
from vmn_exp.core.metric_block import Block, decode_blocks, header_at
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import (
    is_indexed_file,
    is_metric_file,
    metric_writer,
    stream_writer_and_seq,
)
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.storage.s3_base import parallel_map

# An unread part of an object past this is folded from its block headers.
WHOLE_READ_MAX = 16 * 1024 * 1024


def metric_signatures(names):
    """``{name: signature}`` of the metric files among the listed *names*."""
    return {n: list(sig) for n, sig in names.items() if is_metric_file(n)}


def _new_state(sigs=None):
    return {"sig": dict(sigs or {}), "objects": {}, "points": {}, "sums": {}}


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
    """Fold every metric object into *record*'s (fresh) fold: a writer's
    sums when its objects only grew since, then what is not folded yet."""
    old = record.get("metrics") or {}
    record["metrics"] = state = _new_state(metric_state_sigs(record))
    objects = _objects(storage, where)
    for writer in sorted(objects):
        _replay(record["fold"], state, old, writer, objects[writer])
    _fold_unread(record["fold"], state, storage, where, objects)


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
    for writer in sorted(objects):
        folded = any(metric_writer(n) == writer for n in state["objects"])
        if folded and _newly_indexed(state, objects, writer) and not adopted(
                state, storage, where, writer, objects[writer][0]):
            return False
    if not _grew_only(state, objects):
        return False
    _fold_unread(fold, state, storage, where, objects)
    return True


def _fold_unread(fold, state, storage, where, objects):
    todo = [(writer, name, size) for writer in sorted(objects)
            for name, size in objects[writer] if state["objects"].get(name, 0) < size]
    readers = parallel_map(lambda item: _reader(state, storage, where, *item[1:]), todo)
    for (writer, name, size), reader in zip(todo, readers):
        _fold_object(fold, state, writer, name, size, reader)
    for writer, objs in objects.items():
        if len(objs) == 1 and is_indexed_file(objs[0][0]):
            state.get("sums", {}).pop(writer, None)
            state.get("tails", {}).pop(writer, None)


def _replay(fold, state, old, writer, objects):
    """Fold *writer*'s sums of the *old* state when its objects only grew
    since (no new ``.vmx``) and no rewind the fold knows may hide their points."""
    sums = (old.get("sums") or {}).get(writer)
    if sums is None or may_be_rewound(fold, {"keys": list(sums.values())}):
        return
    mine = {n: c for n, c in old["objects"].items() if metric_writer(n) == writer}
    sizes = dict(objects)
    if any(sizes.get(n, -1) < c for n, c in mine.items()) or any(
            is_indexed_file(n) and mine.get(n) != size for n, size in sizes.items()):
        return
    apply_sums(fold, writer, sums)
    state["objects"].update(mine)
    state["points"][writer] = old["points"][writer]
    state["sums"][writer] = sums
    tail = (old.get("tails") or {}).get(writer)
    if tail:
        state.setdefault("tails", {})[writer] = tail


def _reader(state, storage, where, name, size):
    """What folds *name*'s unread part: its :class:`MetricIndexReader`, else
    ``read(offset, length)`` — over the part's bytes read whole when the
    object never grows (a synced segment, any remote object; one GET instead
    of two per block), not too big; a local live stream's body stays unread."""
    read = lambda off, n: storage.read_range(*where, name, off, n)  # noqa: E731
    if is_indexed_file(name):
        return MetricIndexReader(read, size)
    consumed = state["objects"].get(name, 0)
    fixed = stream_writer_and_seq(name)[1] or getattr(storage, "is_remote", lambda: False)()
    if not fixed or size - consumed > WHOLE_READ_MAX:
        return read
    data = read(consumed, size - consumed) or b""
    return lambda off, n: data[off - consumed:off - consumed + n]


def _fold_object(fold, state, writer, name, size, reader):
    if is_indexed_file(name):
        _fold_indexed(fold, state, writer, reader)
        state["objects"][name] = size
        return
    consumed, added = state["objects"].get(name, 0), {}
    while True:
        found = header_at(reader, consumed, size)
        if found is None:
            break
        header, length = found
        start = consumed
        _fold_block(fold, state, writer, header,
                    lambda: decode_blocks(reader(start, length) or b""))
        for entry in header["keys"]:
            added[entry["k"]] = added.get(entry["k"], 0) + entry["n"]
        consumed += length
    state["objects"][name] = consumed
    note_tail(state, writer, name, added)


def _fold_block(fold, state, writer, header, decoded):
    """Fold one block from its *header*, or point by point from *decoded()*
    (its :class:`Block` s) when a known rewind may hide some of them; its
    header widens the writer's sums, kept from the writer's first point on."""
    base = state["points"].get(writer, 0)
    sums = state.setdefault("sums", {})
    if not base:
        sums[writer] = {}
    if writer in sums:
        add_block(sums[writer], base, header)
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
