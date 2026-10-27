#!/usr/bin/env python3
"""Which of a record's listed log files :mod:`parsed_logs` reads, in which
order, and when what it parsed no longer holds. Pure: no I/O."""
from vmn_exp.core.logfiles import (
    appended,
    group_log_names,
    is_log_file,
    writer_and_span,
)
from vmn_exp.core.metric_files import (
    group_metric_names,
    is_indexed_file,
    is_stream_file,
)
from vmn_exp.core.rewind import REWIND


def visible(names):
    """``{stream: [files]}`` a full read reads, in its order: each stream's
    logs, then its metric objects — less what a compaction or seal covers."""
    groups = {}
    for writer, group in group_log_names(names).items():
        groups.setdefault(writer, []).extend(group)
    for writer, group in group_metric_names(names).items():
        groups.setdefault(writer, []).extend(group)
    return groups


def by_writer(groups, entries_of):
    """``{stream: entries}`` of the files *groups* list, from *entries_of*."""
    return {w: [e for name in names for e in entries_of.get(name, ())]
            for w, names in groups.items()}


def _merged_log(name):
    return is_log_file(name) and _span(name)[0] < _span(name)[1]


def _span(name):
    return writer_and_span(name)[1]


def merges(name):
    """Whether *name* replaces other files: a compacted log or a ``.vmx``."""
    return is_indexed_file(name) or _merged_log(name)


def adopt_merges(files, offsets, read):
    """``(offsets, read)`` with each newly listed compacted log in *files*
    standing for the parts of it read in full — it is their bytes
    concatenated, so the entries read are its entries, and nothing is read."""
    offsets, read = dict(offsets), dict(read)
    for name in [n for n in files if n not in offsets and _merged_log(n)]:
        writer, (first, last) = writer_and_span(name)
        parts = sorted((m for m in offsets if is_log_file(m) and writer_and_span(m)[0] == writer
                        and first <= _span(m)[0] <= last), key=_span)
        if not _tiles(parts, first, last) or sum(offsets[m] for m in parts) != files[name][0]:
            continue
        read[name] = [e for m in parts for e in read.pop(m, ())]
        offsets[name] = files[name][0]
        for m in parts:
            del offsets[m]
    return offsets, read


def _tiles(parts, first, last):
    """Whether the spans of *parts* (in order) cover ``first..last`` exactly."""
    expected = first
    for part in parts:
        start, end = _span(part)
        if start != expected:
            return False
        expected = end + 1
    return expected == last + 1


def appends_in_order(entries, new_entries):
    """Whether *new_entries* all sort after *entries* in the merged log — and
    carry no rewind, which may hide some of *entries*."""
    if entries and any(e.get("type") == REWIND for e in new_entries):
        return False
    stamps = [e.get("timestamp", "") for e in new_entries]
    if not all(isinstance(ts, str) for ts in stamps):
        return False
    if not entries or not stamps:
        return True
    last = entries[-1].get("timestamp", "")
    return isinstance(last, str) and min(stamps) > last


def _grows_in_place(name):
    """Whether a file listed again under its name may only have grown: a
    JSONL log or a metric stream — never a ``.vmx``, which a rewind rebuilds."""
    return is_log_file(name) or is_stream_file(name)


def replaced(sig, files, in_place=True):
    """Whether a file of listing *sig* (the last parse's) changed since other
    than by an append (:func:`~vmn_exp.core.logfiles.appended`) — like a log a
    local-first cache merged — so its bytes past the offset parsed need not
    follow the ones parsed. Without *in_place* (an object store, whose
    segments are written once) any change under a name replaced the file."""
    before = dict(sig or ())
    return any(
        name in before and before[name] != listed
        and not (in_place and _grows_in_place(name) and appended(before[name], listed))
        for name, listed in files.items()
    )
