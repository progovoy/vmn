#!/usr/bin/env python3
"""Which outer run an outer run is compared with (plan 28 N3): among the
outer runs beside it (the same parent; top-level ones for a top-level run)
with equal values on the match fields (``params.<k>``/``tags.<k>``) and a
different one on each differ field (plan 34 §2; missing is no peer), the
latest one tagged ``baseline=true``, else the latest that ended before it
was created. A ``?to=`` overrides both (the route's). Pure.
"""
from vmn_exp.core.settle import row_closes
from vmn_exp.ui.leaderboard_group_fields import value_of

PINNED, LATEST = "pinned", "latest"


def recency(row):
    """A row's place by creation (ties: its verstr)."""
    return (row.get("timestamp") or "", row["verstr"])


def is_pinned(row):
    return str((row.get("tags") or {}).get("baseline", "")).lower() == "true"


def _readers(target, fields):
    """*fields*' readers and *target*'s values on them."""
    readers = [value_of(field) for field in fields]
    return readers, [read(target) for read in readers]


def _alike(target, fields):
    readers, wanted = _readers(target, fields)
    return lambda row: [read(row) for read in readers] == wanted


def _unlike(target, fields):
    """Whether a row has a value on every *fields* and none equal to
    *target*'s; a missing value is never different."""
    readers, ours = _readers(target, fields)
    if None in ours:
        return lambda row: False
    return lambda row: all(read(row) not in (None, mine) for read, mine in zip(readers, ours))


def choose_baseline(target, candidates, fields, differ=()):
    """``(row, "pinned"|"latest")`` of *target*'s baseline among the rows
    *candidates* equal on *fields* and different on *differ*, else
    ``(None, None)``."""
    alike, unlike = _alike(target, fields), _unlike(target, differ)
    rows = [r for r in candidates if r["verstr"] != target["verstr"] and alike(r) and unlike(r)]
    pinned = [r for r in rows if is_pinned(r)]
    if pinned:
        return max(pinned, key=recency), PINNED
    before = recency(target)
    ended = [r for r in rows if row_closes(r) and recency(r) < before]
    return (max(ended, key=recency), LATEST) if ended else (None, None)
