#!/usr/bin/env python3
"""What :mod:`vmn_exp.core.index` hands out of a snapshot and keeps of a
refreshed record."""


def row_copies(snap, with_create_note):
    """Copies of *snap*'s rows with their ``metric_summary`` and ``outputs``
    (and create note)."""
    rows = [
        dict(
            row,
            metric_summary=snap.metric_summary(row["verstr"]),
            outputs=dict(snap.outputs_of(row["verstr"])),
        )
        for row in snap.rows
    ]
    if with_create_note:
        for row in rows:
            row["create_note"] = snap.create_notes[row["verstr"]]
    return rows


def adopted(old, record, state_moved):
    """*record* as refreshed. A copy back from the helper process keeps
    *old*'s run state object unless it moved: readers diff generations by
    identity."""
    if old is not None and record is not old and not state_moved:
        record["run_state"] = old["run_state"]
    return record
