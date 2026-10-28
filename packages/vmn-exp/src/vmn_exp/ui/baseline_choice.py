#!/usr/bin/env python3
"""Which outer run an outer run is compared with (plan 28 N3): among the
outer runs beside it (the same parent; top-level ones for a top-level run)
with equal values on the match fields (``params.<k>``/``tags.<k>``), the
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


def _alike(target, fields):
    readers = [value_of(field) for field in fields]
    wanted = [read(target) for read in readers]
    return lambda row: [read(row) for read in readers] == wanted


def choose_baseline(target, candidates, fields):
    """``(row, "pinned"|"latest")`` of *target*'s baseline among the rows
    *candidates*, else ``(None, None)``."""
    alike = _alike(target, fields)
    rows = [r for r in candidates if r["verstr"] != target["verstr"] and alike(r)]
    pinned = [r for r in rows if is_pinned(r)]
    if pinned:
        return max(pinned, key=recency), PINNED
    before = recency(target)
    ended = [r for r in rows if row_closes(r) and recency(r) < before]
    return (max(ended, key=recency), LATEST) if ended else (None, None)
