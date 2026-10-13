#!/usr/bin/env python3
"""A failed or stuck run's failure signature, from its row fields.

Runs that failed for the same reason should cluster, so the signature keeps
the shape of what went wrong (status, ``end_reason``, ``signal``,
``exit_code`` and the ``error_summary`` text) and masks what differs per
run: uuids, versions, paths, hex ids and numbers. "CUDA out of memory.
Tried to allocate 2.31 GiB" and "... 1.07 GiB" give the same signature.
"""
import re

from vmn_exp.core.status import FAILED, STUCK

MAX_MESSAGE = 160
_MSG = " | msg="
_MASKS = [
    (re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE), "<uuid>"),
    (re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?(?:\+[\w.]+)?"), "<ver>"),
    (re.compile(r"(?<![\w.<>])(?:~|\.{1,2})?(?:/[\w.\-+@%=]+)+/?"), "<path>"),
    (re.compile(r"\b[A-Za-z]:\\[\w\\.\-]+"), "<path>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.IGNORECASE), "<hex>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,}\b", re.IGNORECASE), "<hex>"),
    (re.compile(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"), "<n>"),
]


def mask(text):
    """*text* with per-run detail masked and whitespace collapsed."""
    for pattern, placeholder in _MASKS:
        text = pattern.sub(placeholder, text)
    return " ".join(text.split())[:MAX_MESSAGE]


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
    return sig + _MSG + message if message else sig


def label(sig):
    """Human text for a :func:`signature`, or None."""
    if sig is None:
        return None
    head, _, message = sig.partition(_MSG)
    status, *fields = head.split(" | ")
    detail = dict(field.split("=", 1) for field in fields)
    notes = [detail["reason"]] if "reason" in detail else []
    if "signal" in detail:
        notes.append(f"signal {detail['signal']}")
    if "exit" in detail:
        notes.append(f"exit {detail['exit']}")
    text = message or ("Stuck: no heartbeat" if status == STUCK else "Failed")
    return f"{text} ({', '.join(notes)})" if notes else text
