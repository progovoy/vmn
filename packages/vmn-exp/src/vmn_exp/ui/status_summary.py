#!/usr/bin/env python3
"""An app's status counts and the one status that needs attention now (the
shell's rollup): stuck, else a failure in the last ``recent_sec``, else
running. An old failure alone needs none."""
import datetime

from vmn_exp.core.status import parse_iso

STATUSES = ("created", "running", "stuck", "succeeded", "failed")
RECENT_SEC = 86400


def _rollup(counts, failed_recent):
    if counts["stuck"]:
        return "stuck"
    if failed_recent:
        return "failed"
    if counts["running"]:
        return "running"
    return None


def status_summary(rows, now, recent_sec=RECENT_SEC):
    """``{total, counts, failed_recent, recent_sec, rollup}`` of *rows* (with
    derived ``status``) as of *now* (an aware datetime)."""
    counts = dict.fromkeys(STATUSES, 0)
    since = now - datetime.timedelta(seconds=recent_sec)
    failed_recent = 0
    for row in rows:
        status = row.get("status")
        if status in counts:
            counts[status] += 1
        finished = status == "failed" and parse_iso(row.get("finished_at"))
        if finished and finished >= since:
            failed_recent += 1
    return {
        "total": len(rows),
        "counts": counts,
        "failed_recent": failed_recent,
        "recent_sec": recent_sec,
        "rollup": _rollup(counts, failed_recent),
    }
