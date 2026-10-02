"""Comment threads on runs and reports (docs/plans/13-reports-comments.md §3.2).

A run's thread is the record ``comments/<app-key>/<verstr>/``; a report's is
``reports/<rid>/comments/``. Each comment write appends one entry to the
thread's per-writer log; :func:`fold` replays them per comment id, last writer
wins on ``(ts, writer, pos)``, and a delete is a tombstone that keeps replies.
"""
from __future__ import annotations

import base64
import os

from vmn_exp.core.record_format import stamped
from vmn_exp.core.writer import claim_record, flush_log, get_writer_id
from vmn_exp.registry.fold import next_ts, now_iso
from vmn_exp.registry.log import actor_identity
from vmn_exp.storage.areas import COMMENTS, REPORTS

REPORT_THREAD = "comments"


def _location(storage, target):
    """``(area storage, scope, name, target dict)`` of *target*'s thread."""
    if target[0] == "run":
        _, app, verstr = target
        return storage.in_area(COMMENTS), app, verstr, {"kind": "run", "app": app, "verstr": verstr}
    _, rid = target
    return storage.in_area(REPORTS), rid, REPORT_THREAD, {"kind": "report", "rid": rid}


def _entries(area, scope, name):
    if not area.exists(scope, name):
        return []
    return area.load_merged_log(scope, name)


def thread(storage, target):
    """The folded comments of *target*, in posting order."""
    area, scope, name, _ = _location(storage, target)
    return fold(_entries(area, scope, name))


def add(storage, target, text, reply_to=None, anchor=None, author=None):
    """Post a comment on *target*; returns its id."""
    area, scope, name, target_dict = _location(storage, target)
    header = {"verstr": name, "type": "comment_thread", "target": target_dict, "timestamp": now_iso()}
    claim_record(area, scope, name, stamped(header))  # losing the race is fine
    comment_id = "c" + base64.b32encode(os.urandom(10)).decode().lower()
    _append(area, scope, name, "comment", id=comment_id, text=text,
            reply_to=reply_to, anchor=anchor,
            author=author if author is not None else actor_identity())
    return comment_id


def edit(storage, target, comment_id, text):
    _append(*_location(storage, target)[:3], "comment_edit", id=comment_id, text=text)


def delete(storage, target, comment_id):
    _append(*_location(storage, target)[:3], "comment_delete", id=comment_id)


def resolve(storage, target, comment_id, resolved=True):
    _append(*_location(storage, target)[:3], "comment_resolve",
            id=comment_id, resolved=resolved)


def delete_thread(storage, target):
    area, scope, name, _ = _location(storage, target)
    area.delete(scope, name)


def _append(area, scope, name, entry_type, **fields):
    entries = _entries(area, scope, name)
    writer = get_writer_id()
    entry = {
        "type": entry_type,
        "ts": next_ts(max((e.get("ts", "") for e in entries), default=None), now_iso()),
        "writer": writer,
        "pos": sum(1 for e in entries if e.get("writer") == writer),
        "actor": actor_identity(),
        **fields,
    }
    area.append_log_entry(scope, name, writer, entry)
    flush_log(area, scope, name)


def _order(entry):
    return (entry.get("ts") or "", entry.get("writer") or "", entry.get("pos") or 0)


def fold(entries):
    """Fold thread *entries* into comments, ordered by their posting."""
    comments = {}
    for entry in sorted(entries, key=_order):
        kind, cid = entry.get("type"), entry.get("id")
        if kind == "comment":
            comments.setdefault(cid, _new_comment(entry))
        elif cid in comments:
            _apply(comments[cid], kind, entry)
    return list(comments.values())


def _new_comment(entry):
    keys = ("id", "ts", "writer", "author", "text", "reply_to", "anchor")
    return {**{k: entry.get(k) for k in keys}, "resolved": False, "deleted": False}


def _apply(comment, kind, entry):
    if comment["deleted"]:
        return
    if kind == "comment_edit":
        comment["text"] = entry.get("text")
    elif kind == "comment_resolve":
        comment["resolved"] = bool(entry.get("resolved", True))
    elif kind == "comment_delete":
        comment.update(deleted=True, text=None)
