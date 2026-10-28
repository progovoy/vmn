#!/usr/bin/env python3
"""An app's status counts and the one status that needs attention now (the
shell's rollup): stuck, else a failure in the last ``recent_sec``, else
running. An old failure alone needs none. Runs an ended outer run settled
(:mod:`~vmn_exp.core.settle`) count as ``never_started``/``lost`` beside
the counts, never in them: a lost run needs no look of its own."""
import datetime

from vmn_exp.core.settle import SETTLED, counted_status
from vmn_exp.core.status import CREATED, FAILED, RUNNING, STUCK, SUCCEEDED, parse_iso

STATUSES = (CREATED, RUNNING, STUCK, SUCCEEDED, FAILED)
RECENT_SEC = 86400


def _rollup(counts, failed_recent):
    if counts[STUCK]:
        return STUCK
    if failed_recent:
        return FAILED
    if counts[RUNNING]:
        return RUNNING
    return None


def status_summary(rows, now, recent_sec=RECENT_SEC):
    """``{total, counts, never_started, lost, failed_recent, rollup}`` of
    *rows* (with derived ``status`` and ``settled``) as of *now* (an aware
    datetime)."""
    counts, settled = dict.fromkeys(STATUSES, 0), dict.fromkeys(SETTLED, 0)
    since = now - datetime.timedelta(seconds=recent_sec)
    failed_recent = 0
    for row in rows:
        status = counted_status(row)
        (settled if status in settled else counts)[status] += 1
        finished = status == FAILED and parse_iso(row.get("finished_at"))
        if finished and finished >= since:
            failed_recent += 1
    return summary_payload(len(rows), counts, settled, failed_recent)


def tallied_summary(parts, now, recent_sec=RECENT_SEC):
    """:func:`status_summary` of the rows job rollup *parts* tally
    (:class:`~vmn_exp.ui.job_tally.Tally`), recent failures by finish minute."""
    counts, settled = dict.fromkeys(STATUSES, 0), dict.fromkeys(SETTLED, 0)
    for part in parts:
        for status, n in part.counts.items():
            (settled if status in settled else counts)[status] += n
    minute = int(now.timestamp() // 60)
    failed_recent = sum(p.timeline[FAILED].recent(minute, recent_sec // 60) for p in parts)
    total = sum(counts.values()) + sum(settled.values())
    return summary_payload(total, counts, settled, failed_recent)


def summary_payload(total, counts, settled, failed_recent):
    """What :func:`status_summary` answers for these tallies."""
    return {
        "total": total,
        "counts": counts,
        **settled,
        "failed_recent": failed_recent,
        "rollup": _rollup(counts, failed_recent),
    }
