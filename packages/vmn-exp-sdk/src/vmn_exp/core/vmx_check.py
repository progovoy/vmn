#!/usr/bin/env python3
"""The light check of a record folded before records 20 from ``.vmx`` files.

Such a fold may hold an older footer's step ends as a metric's first/last
write, and lacks the step restart mark. Most compacted runs' steps rose, so
both are right: :func:`needs_refold` tells the others from the run's
``.vmx`` footers alone — one tail read each, plus an older footer's stepped
keys' timestamps column (:mod:`~vmn_exp.core.vmx_write_order`) — folding
them as the index would: an older footer whose write-order ends differ from
its stored ones, or a metric whose last write is below its highest step,
needs the record folded again. An object gone since the record's listing
does too (the refold lists afresh).
"""
from vmn_exp.core.fold import new_fold
from vmn_exp.core.fold_blocks import apply_header, footer_entries
from vmn_exp.core.fold_steps import step_restarts
from vmn_exp.core.index_metric_reads import MetricObjectGone, object_read
from vmn_exp.core.metric_block import has_restart_points
from vmn_exp.core.metric_files import is_indexed_file, metric_writer
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.vmx_write_order import indexed_entries


def indexed_objects(record):
    """``{name: size}`` of the ``.vmx`` objects *record* (or its head) folded."""
    objects = (record.get("metrics") or {}).get("objects") or {}
    return {name: size for name, size in objects.items() if is_indexed_file(name)}


def needs_refold(storage, where, objects):
    """Whether the record *where* (``(app, key)``), whose ``.vmx`` *objects*
    (``{name: size}``, :func:`indexed_objects`) its fold read, must be folded
    again."""
    fold = new_fold()
    try:
        for name, size in sorted(objects.items()):
            reader = MetricIndexReader(object_read(storage, where, name), size)
            entries = indexed_entries(reader)
            if not has_restart_points(reader.footer) and entries != footer_entries(reader.footer):
                return True
            apply_header(fold, metric_writer(name), 0, {"keys": entries})
    except MetricObjectGone:
        return True
    return bool(step_restarts(fold))
