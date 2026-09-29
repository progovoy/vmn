#!/usr/bin/env python3
"""Rewinding a run's history: the ``rewind`` log entry and who it hides.

A log is append-only — across writers, local files and S3 segments — so a
rewind cannot delete anything. It appends ``{"type": "rewind", "step": N}``
instead, and every reader skips each entry with a step past N that sorts
*before* that marker in the merged log. Entries after the marker count, so a
run rewound to N simply continues from N + 1. Entries without a step (params,
notes, tags, ...) are never rewound.

Pure: no storage, no clock (beyond the new entry's timestamp).
"""
from vmn_exp._base import now_iso

REWIND = "rewind"


def create_rewind_entry(step):
    """The log entry that rewinds a run to *step*."""
    return {"timestamp": now_iso(), "type": REWIND, "step": int(step)}


def entry_step(entry):
    """*entry*'s numeric ``step``, or None."""
    step = entry.get("step")
    if isinstance(step, bool) or not isinstance(step, (int, float)):
        return None
    return step


def rewind_step(entry):
    """The step a ``rewind`` entry rewinds to; None for any other entry."""
    return entry_step(entry) if entry.get("type") == REWIND else None


def is_rewound(rewinds, entry, key):
    """Whether *entry* (at merge-order *key*) is hidden by one of *rewinds*.

    *rewinds* are ``[step, *key]`` lists: a marker hides every stepped entry
    past its step whose key is smaller than its own.
    """
    if not rewinds or entry.get("type") == REWIND:
        return False
    step = entry_step(entry)
    if step is None:
        return False
    return any(r[0] < step and key < tuple(r[1:]) for r in rewinds)


def drop_rewound(entries):
    """*entries* (a merged, ordered log) without the ones a later rewind hides
    — :func:`is_rewound` keyed by log position, as the fold keys its own."""
    markers = [
        [rewind_step(e), pos]
        for pos, e in enumerate(entries)
        if isinstance(e, dict) and rewind_step(e) is not None
    ]
    if not markers:
        return entries
    return [
        e for pos, e in enumerate(entries)
        if not (isinstance(e, dict) and is_rewound(markers, e, (pos,)))
    ]


def rewinds_of(log):
    """``[{"step", "timestamp"}]`` of every rewind in *log*, in log order."""
    return [
        {"step": rewind_step(e), "timestamp": e.get("timestamp")}
        for e in log
        if isinstance(e, dict) and rewind_step(e) is not None
    ]
