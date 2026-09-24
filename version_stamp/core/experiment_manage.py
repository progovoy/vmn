#!/usr/bin/env python3
"""Changing a stored experiment after the fact: archiving and tags.

Both are safe on a finished run and never touch its results. Archiving is a
metadata field (``archived: true``, rewritten atomically on disk and under the
ETag on S3 by the backend's ``update_metadata``); listings hide archived runs
unless asked, and nothing else treats them differently — prune included. Tags
are ``tags`` log entries, folded per key, last write wins.

Shared by ``vmn exp tag/archive/unarchive`` and ``version_stamp.exp.manage``.
Storage is duck-typed; like the rest of ``core`` this imports nothing from
``cli``, ``ui`` or ``exp``.
"""
from version_stamp.core.experiment_writer import (
    create_tags_entry,
    flush_log,
    get_writer_id,
)

ARCHIVED_FIELD = "archived"


def set_archived(storage, app_name, verstr, archived=True):
    """Archive (or unarchive) *verstr*; False when there is no such record."""
    update = {ARCHIVED_FIELD: True if archived else None}
    return bool(storage.update_metadata(app_name, verstr, update))


def tag_run(storage, app_name, verstr, tags=None, remove=None):
    """Set *tags* and drop the *remove* keys on *verstr*; False when there is
    no such record. ValueError for an empty change or a bad key.

    A one-shot call: no run supervisor or SDK heartbeat is around to flush
    this to the remote later, so it is flushed right here.
    """
    entry = create_tags_entry(tags, remove)
    if not storage.exists(app_name, verstr):
        return False
    if storage.append_log_entry(app_name, verstr, get_writer_id(), entry) is False:
        return False
    flush_log(storage, app_name, verstr)
    return True
