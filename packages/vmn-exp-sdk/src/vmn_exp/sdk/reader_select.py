#!/usr/bin/env python3
"""Which rows :func:`vmn_exp.sdk.reader.list_runs` returns, and what it does
when its index is still loading (plan 41 D9). Pure: rows and a loading state
in, rows or an :class:`IndexingWarning` out."""
import warnings

from vmn_exp.core.load_progress import IndexingWarning, incomplete_text
from vmn_exp.core.log import sort_by_metric

INCOMPLETE_CHOICES = ("warn", "raise")
KEEP_PARTIAL_HINT = '; pass incomplete="warn" to get the rows loaded so far'


def select(rows, schema, *, last=None, sort=None, descending=None, limit=None):
    """*rows* cut to the *last* N (storage order), sorted (see
    :func:`~vmn_exp.core.log.sort_by_metric`), then cut to the first *limit*:
    ``limit`` is a top-N, ``last`` the newest N. Raises ValueError unless
    *limit* is None or a positive int."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError(f"limit must be a positive int, not {limit!r}")
    if last:
        rows = rows[-int(last) :]
    rows = sort_by_metric(rows, schema, sort=sort, descending=descending)
    return rows if limit is None else rows[:limit]


def check_loading(loading, incomplete, stacklevel):
    """Act on a snapshot's *loading* state (None once loaded): raise
    :class:`IndexingWarning` unless *incomplete* is ``"warn"``, which warns it
    instead, attributed *stacklevel* frames up (1: the caller of this). Raises
    ValueError for an *incomplete* other than None, ``"warn"``, ``"raise"``."""
    if incomplete is not None and incomplete not in INCOMPLETE_CHOICES:
        raise ValueError(f'incomplete must be "warn" or "raise", not {incomplete!r}')
    if loading is None:
        return
    text = incomplete_text(loading)
    if incomplete == "warn":
        warnings.warn(text, IndexingWarning, stacklevel=stacklevel + 1)
        return
    raise IndexingWarning(text + KEEP_PARTIAL_HINT)
