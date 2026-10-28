#!/usr/bin/env python3
"""A failed or stuck run's failure signature, from its row fields.

Runs that failed for the same reason should cluster, so the signature keeps
the shape of what went wrong (status, ``end_reason``, ``signal``,
``exit_code`` and the ``error_summary`` text) and masks what differs per
run (:func:`~vmn_exp.core.text_mask.mask`): uuids, versions, paths, hex ids
and numbers. "CUDA out of memory. Tried to allocate 2.31 GiB" and "...
1.07 GiB" give the same signature. A run without an ``error_summary``
clusters by its latest note signature (``note_sig``, plan 28 N7) instead.

:func:`signed` gives a board row its ``failure_sig`` and, from the run's note
signatures (``IndexSnapshot.notes_of``), its ``note_sig`` and
``note_minutes`` (what a job timeline counts, :mod:`~vmn_exp.ui.job_tally`).
"""
from vmn_exp.core.note_sigs import last_note_sig, note_minutes
from vmn_exp.core.status import FAILED, STUCK
from vmn_exp.core.text_mask import mask

_MSG, _NOTE = " | msg=", " | note="


def signature(row):
    """A short stable string for a failed or stuck *row*, else None."""
    status = row.get("status")
    if status not in (FAILED, STUCK):
        return None
    parts = [status]
    for field, key in (("exit_code", "exit"), ("signal", "signal"), ("end_reason", "reason")):
        if row.get(field) is not None:
            parts.append(f"{key}={row[field]}")
    sig = " | ".join(parts)
    message = mask(str(row.get("error_summary") or ""))
    if message:
        return sig + _MSG + message
    return sig + _NOTE + row["note_sig"] if row.get("note_sig") else sig


def signed(row, notes=None):
    """*row* with its ``failure_sig`` (plan 23 S2) and, when the run has
    note signatures *notes*, its ``note_sig``/``note_minutes``, set in place."""
    if notes:
        row["note_sig"], row["note_minutes"] = last_note_sig(notes), note_minutes(notes)
    row["failure_sig"] = signature(row)
    return row


def label(sig):
    """Human text for a :func:`signature`, or None."""
    if sig is None:
        return None
    head, _, message = sig.partition(_MSG)
    head, _, note = head.partition(_NOTE)
    status, *fields = head.split(" | ")
    detail = dict(field.split("=", 1) for field in fields)
    notes = [detail["reason"]] if "reason" in detail else []
    if "signal" in detail:
        notes.append(f"signal {detail['signal']}")
    if "exit" in detail:
        notes.append(f"exit {detail['exit']}")
    if not message:
        message = f"Last note: {note}" if note else None
    text = message or ("Stuck: no heartbeat" if status == STUCK else "Failed")
    return f"{text} ({', '.join(notes)})" if notes else text
