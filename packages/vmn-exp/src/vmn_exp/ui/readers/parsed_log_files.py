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


def merges(name):
    """Whether *name* replaces other files: a compacted log or a ``.vmx``."""
    if is_indexed_file(name):
        return True
    first, last = writer_and_span(name)[1]
    return is_log_file(name) and first < last


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
