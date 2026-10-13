#!/usr/bin/env python3
"""A job's timeline (plan 23 S3): runs started, succeeded and failed per
minute, read off its subtree's :class:`~vmn_exp.ui.job_tally.Tally` parts.

Per minute while every run of the job falls in the day before its newest
minute (each per-minute series then holds every run its 10-minute one
does), else per 10 minutes, which are exact for all time. Buckets are
sparse: only the ones something happened in, oldest first; how many runs
were running at a time is for the client to derive.
"""
from vmn_exp.ui.job_tally import COARSE_MINUTES, MINUTES_KEPT, TIMELINE


def _complete(series, floor):
    """Whether *series*' per-minute counts hold all its runs, from *floor* on."""
    return (sum(series.minutes.values()) == sum(series.coarse.values())
            and all(minute >= floor for minute in series.minutes))


def _per_minute(all_series):
    newest = max((max(s.minutes) for s in all_series if s.minutes), default=None)
    floor = newest - MINUTES_KEPT if newest is not None else 0
    return all(_complete(s, floor) for s in all_series)


def timeline(parts):
    """``{bucket_sec, start, buckets: [{t, started, succeeded, failed}]}``;
    ``t`` is a bucket's start in epoch seconds."""
    named = [(name, part.timeline[name]) for part in parts for name in TIMELINE]
    fine = _per_minute([series for _, series in named])
    bucket_sec = 60 if fine else 60 * COARSE_MINUTES
    buckets = {}
    for name, series in named:
        for key, count in (series.minutes if fine else series.coarse).items():
            bucket = buckets.setdefault(key * bucket_sec, dict.fromkeys(TIMELINE, 0))
            bucket[name] += count
    out = [dict(t=t, **buckets[t]) for t in sorted(buckets)]
    return {"bucket_sec": bucket_sec, "start": out[0]["t"] if out else None, "buckets": out}
