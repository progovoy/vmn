#!/usr/bin/env python3
"""Merge a finished record's remote log segments, one object per stream.

A run syncing to a remote store ships a log segment per sync; one that died
(failed, stuck) never merged them, so every cold index load paid a GET for
each. Only call it once the record's writers are done: an append racing the
merge could be deleted with it (``compact_log_segments``).
"""


def compact_record_logs(storage, app_name, verstr):
    """The streams of *verstr* whose log segments were merged, sorted."""
    remote_for = getattr(storage, "remote_for", None)
    target = remote_for(app_name, verstr) if remote_for else storage
    compact = getattr(target, "compact_log_segments", None)
    if compact is None:
        return []
    groups = target.log_object_groups(app_name, verstr)
    return [stream for stream in sorted(groups)
            if len(groups[stream]) > 1 and compact(app_name, verstr, stream)]
