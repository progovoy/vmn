#!/usr/bin/env python3
"""The attention parts every app has (:mod:`~vmn_exp.ui.attention`), shown
before the configured ones and only while they count any: ``outlived``, the
runs an ended outer run left still running (plan 28 T2b,
:mod:`~vmn_exp.core.settle`).

An outlived run is running, so it is one of the base's live rows: counting
reads those as of the time bucket, O(live), and never sorts the board.
"""
from vmn_exp.core.settle import OUTLIVED
from vmn_exp.ui.leaderboard_scope import Filters, filtered

OUTLIVED_PART = {"key": OUTLIVED, "label": "outlived their outer run",
                 "query": f'settled = "{OUTLIVED}"', "level": "warn"}
BUILT_IN = (OUTLIVED_PART,)


def with_built_in(entries):
    """The built-in parts, then the configured *entries*."""
    return [*BUILT_IN, *entries]


def is_built_in(key):
    return key in _ROWS


def shown(key, count):
    """Whether a part of *key* counting *count* is shown: a built-in one
    only while it counts any."""
    return not is_built_in(key) or bool(count)


def built_in_count(cache, snapshot, key, scope=None):
    """How many non-archived runs (of *scope*'s subtree) built-in part *key* counts."""
    return len(built_in_rows(cache, snapshot, key, scope))


def built_in_rows(cache, snapshot, key, scope=None):
    """The non-archived runs (of *scope*'s subtree) built-in part *key* counts."""
    return _ROWS[key](cache, snapshot, scope)


def _outlived(cache, snapshot, scope):
    base, bucket = cache._base(snapshot)
    patched = base.patched(bucket)
    live = [patched.get(i, base.rows[i]) for i in base.patch.live]
    return [row for row in filtered(snapshot, live, Filters(scope=scope))
            if row.get("settled") == OUTLIVED]


_ROWS = {OUTLIVED: _outlived}
