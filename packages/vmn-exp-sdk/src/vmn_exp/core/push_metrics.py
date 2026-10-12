"""Metric objects (plan 12) for ``vmn exp push``.

A local stream is this copy's own (:mod:`vmn_exp.core.streams`): its intact
blocks past what the remote holds go as the next segment, created only if it
does not exist, as a live ship does. A local ``.vmx`` goes through
``put_indexed`` covering every segment the remote holds of its stream (the
local file it was built from held them all). A stream the remote compacted
while blocks of it were still local is compacted locally first and pushed
as that ``.vmx``. Only the root's own streams go: another owner's local
file (a ``cp -r`` of its root, a stream the copy inherited) is pushed only
by that owner, or once adopted (:mod:`vmn_exp.core.adopt`).
"""
import os

from vmn_exp.core.metric_block import intact_length
from vmn_exp.core.metric_compact import compact_writer, record_rewinds
from vmn_exp.core.metric_files import (
    covered_seq,
    is_indexed_file,
    is_stream_file,
    last_seq,
    stream_name,
)
from vmn_exp.core.streams import owned_by


def push_metrics(local, target, app_name, verstr):
    """Upload what the remote lacks of each local metric stream."""
    objects = local.metric_objects(app_name, verstr)
    if not objects:
        return
    remote = target.metric_objects(app_name, verstr)
    owns = owned_by(local.stream_owners(app_name, verstr))
    for writer in sorted(filter(owns, objects)):
        names, theirs = objects[writer], remote.get(writer, [])
        if any(is_stream_file(n) for n, _ in names) and _compacted(theirs):
            compact_writer(local, app_name, verstr, writer,
                           record_rewinds(local, app_name, verstr))
            names = local.metric_objects(app_name, verstr).get(writer, [])
        _push_stream(local, target, app_name, verstr, writer, names, theirs)


def _compacted(objects):
    return any(is_indexed_file(n) for n, _ in objects)


def _push_stream(local, target, app_name, verstr, writer, names, theirs):
    sizes = dict(theirs)
    record_dir = local.local_record_dir(app_name, verstr)
    for name, size in names:
        if is_indexed_file(name):
            if sizes.get(name) != size:
                covers = max(covered_seq(name), last_seq(n for n, _ in theirs))
                target.put_indexed(app_name, verstr, writer, os.path.join(record_dir, name),
                                   replace=True, covers=covers)
        elif is_stream_file(name):
            _push_blocks(local, target, app_name, verstr, writer, theirs)


def _push_blocks(local, target, app_name, verstr, writer, theirs):
    offset = sum(size for _, size in theirs)
    data = local.read_file_from(app_name, verstr, stream_name(writer), offset) or b""
    chunk = data[: intact_length(data)]
    if not chunk:
        return
    seq = last_seq(n for n, _ in theirs) + 1
    if not target.create_metric_segment(app_name, verstr, writer, seq, chunk):
        raise RuntimeError(f"{verstr}: the remote metrics of {writer!r} changed; push again")
