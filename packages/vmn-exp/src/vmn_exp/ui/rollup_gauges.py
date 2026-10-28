#!/usr/bin/env python3
"""An app's rollup gauges on ``/metrics`` (plan 28 T2a), read off the
board's caches as ``experiments-status`` and an outer run's ``summary``
read them: the status counts (:mod:`~vmn_exp.ui.status_counts`), the
attention strip's parts (the built-in ``stuck``/``failed`` in 24 h/
``running``/``outlived``, then the app's queries,
:mod:`~vmn_exp.ui.attention`), and per top-level outer run that is live, or ended within the window, its compact
rollup (:meth:`~vmn_exp.ui.job_rollup_cache.JobRollupCache.job_rollups`;
the Outer runs view's order). An outer run is live while it is running or
a run under it is running, waiting or stuck; an ended one's end is its own
finish, else its runs' last. At most :data:`MAX_OUTER_RUNS` per app: the
live ones first, then the newest.
"""
import datetime

from vmn_exp.core.settle import SETTLED
from vmn_exp.core.status import RUNNING, STUCK, parse_iso
from vmn_exp.ui.attention import attention_payload
from vmn_exp.ui.attention_built_in import BUILT_IN, built_in_count
from vmn_exp.ui.leaderboard_scope import JOBS
from vmn_exp.ui.leaderboard_warm import DEFAULT_SORT
from vmn_exp.ui.prometheus import Family
from vmn_exp.ui.status_summary import STATUSES

MAX_OUTER_RUNS = 200
_ACTIVE = ("running", "waiting", "stuck")

FAMILIES = (
    ("vmn_runs", "Runs per status (archived runs left out), as experiments-status counts them."),
    ("vmn_attention", "Runs in each part of the attention strip: stuck, failed in 24 h,"
                      " running, outlived, then the app's attention queries."),
    ("vmn_job_runs", "Runs per status under a live or recently ended top-level outer run."),
    ("vmn_job_progress", "A live or recently ended top-level outer run's progress, 0 to 1."),
    ("vmn_job_eta_seconds", "Seconds a live top-level outer run has left at its current rate."),
    ("vmn_index_freshness_seconds", "Seconds since the app's index last refreshed."),
)


def new_families():
    """``{name: Family}`` of the gauges, in exposition order."""
    return {name: Family(name, "gauge", text) for name, text in FAMILIES}


def freshness_sample(labels, as_of, now):
    """The ``vmn_index_freshness_seconds`` sample of an index refreshed at wall *as_of*."""
    return ("vmn_index_freshness_seconds", labels, max(0.0, now.timestamp() - as_of))


def app_samples(labels, cache, board, schema, entries, now, ended_sec):
    """``[(gauge, labels, value)]`` of *board* under *labels* (``workspace``/``app``)."""
    summary = cache.status_summary(board, now)
    samples = _counts("vmn_runs", labels, summary["counts"], summary, STATUSES)
    for key, n in ((STUCK, summary["counts"][STUCK]), ("failed", summary["failed_recent"]),
                   (RUNNING, summary["counts"][RUNNING])):
        samples.append(("vmn_attention", dict(labels, key=key), n))
    for part in BUILT_IN:  # zero included, unlike the strip: a gauge's series stays
        key = part["key"]
        samples.append(("vmn_attention", dict(labels, key=key), built_in_count(cache, board, key)))
    for part in attention_payload(cache, board, schema, entries):
        samples.append(("vmn_attention", dict(labels, key=part["key"]), part["count"]))
    rows = cache.ordered(board, schema, sort=DEFAULT_SORT, top=JOBS)
    for row, job in feed_jobs(rows, cache.job_rollups(board, schema), now, ended_sec):
        samples += _job_samples(dict(labels, outer_run=row["verstr"], name=row.get("name") or ""),
                                job)
    return samples


def _counts(gauge, labels, counts, settled, statuses):
    """*counts* per status, then the settled ones *settled* holds apart."""
    return [(gauge, dict(labels, status=s), counts[s]) for s in statuses] + [
        (gauge, dict(labels, status=s), settled[s]) for s in SETTLED]


def _job_samples(labels, job):
    return _counts("vmn_job_runs", labels, job["counts"], job, job["counts"]) + [
        ("vmn_job_progress", labels, job["progress"]),
        ("vmn_job_eta_seconds", labels, job["eta_sec"])]


def feed_jobs(rows, summaries, now, ended_sec):
    """``[(row, summary)]`` of the outer runs of *rows* (newest first) to
    report: the live ones, then those ended within *ended_sec* of *now*."""
    since = now - datetime.timedelta(seconds=ended_sec)
    live, ended = [], []
    for row in rows:
        job = summaries.get(row["verstr"])
        if job is None:
            continue
        if _live(row, job):
            live.append((row, job))
        elif _ended_since(row, job, since):
            ended.append((row, job))
    return (live + ended)[:MAX_OUTER_RUNS]


def _live(row, job):
    return row.get("status") == RUNNING or any(job["counts"][s] for s in _ACTIVE)


def _ended_since(row, job, since):
    ended = (parse_iso(row.get("finished_at")) or parse_iso(job.get("finished_at"))
             or parse_iso(row.get("timestamp")))
    return ended is not None and ended >= since
