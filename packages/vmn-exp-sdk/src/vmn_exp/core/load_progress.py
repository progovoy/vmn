#!/usr/bin/env python3
"""What a reader says of an index snapshot still loading (its ``loading``,
``(rows loaded, rows expected or None)``): ``indexing 120k/734k runs —
results incomplete``, so a partial listing is never taken for the whole app
(plan 33 §2.2)."""


class IndexingWarning(UserWarning):
    """The rows read come from an index still loading: more runs follow."""


def incomplete_text(loading):
    """The line saying a listing over a snapshot *loading* is incomplete."""
    loaded, total = loading
    shown = _count(loaded) if total is None else f"{_count(loaded)}/{_count(total)}"
    return f"indexing {shown} runs — results incomplete"


def _count(n):
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.0f}k"
    return f"{n / 1_000_000:.1f}M"
