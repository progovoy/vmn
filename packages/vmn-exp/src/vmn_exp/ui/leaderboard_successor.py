#!/usr/bin/env python3
"""A base's successor for the same snapshot, once a live outer run went stuck.

A time bucket patches only the live rows and their ancestors
(:mod:`~vmn_exp.ui.leaderboard_live`). A live outer run that goes stuck
closes its children (:mod:`~vmn_exp.core.settle`): its never-started and
stuck descendants settle, which no patch reaches. So the first bucket that
finds one stuck gets a successor base derived from the current one as if a
new generation came in — the live rows re-derived, that outer's subtree
re-settled: O(live + its subtree), once. Checked once per base and bucket,
O(live outer runs).
"""
from vmn_exp.ui.leaderboard_live import is_live


def live_outers(patch, rows):
    """The live rows with children: those whose going stuck needs a successor."""
    return tuple(i for i in patch.live if rows[i]["children"])


def current(base, bucket, follow):
    """*base*, else the newest of its successors as of *bucket*;
    *follow(base)* builds one."""
    while True:
        successor = _successor(base, bucket, follow)
        if successor is None:
            return base
        base = successor


def latest(base, bucket):
    """*base*'s newest successor built by *bucket* — where the next
    generation is derived from (a clock that went back starts earlier)."""
    while base.successor is not None and base.successor.built_bucket <= bucket:
        base = base.successor
    return base


def _successor(base, bucket, follow):
    if base.successor is not None or not base.live_outers or base.outers_checked == bucket:
        return base.successor
    with base.successor_lock:
        if base.successor is None and base.outers_checked != bucket:
            if any(not is_live(base.snapshot, base.rows[i]["verstr"]) for i in base.live_outers):
                base.successor = follow(base)
            base.outers_checked = bucket
    return base.successor
