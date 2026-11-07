"""Plan 32 F2/F3/F14: a Jobs column sorts by what its cell shows, and a
value that can come from two sources names the one it came from: the
declared rate (``job:rate``) apart from the runs' throughput
(``job:throughput``), ``progress_source``, and the "when" time with
``when_source`` (``started``, else ``created``)."""
import datetime

from leaderboard_fleet import T0, iso
from vmn_exp.ui.job_rollup_payload import job_summary
from vmn_exp.ui.job_tally import RollupSpec, Tally
from vmn_exp.ui.leaderboard_jobs import JOB_SORTS, job_sorted
from vmn_exp.ui.rollup_gauges import _job_samples

SPEC = RollupSpec({})
HOUR_AGO = iso(T0 - datetime.timedelta(hours=1))
TWO_HOURS_AGO = iso(T0 - datetime.timedelta(hours=2))
CREATED = iso(T0 - datetime.timedelta(hours=3))


def _rows(n, **extra):
    return [{"verstr": f"v{i:03d}", "parent": "job", "status": "succeeded", "metrics": {},
             "exit_code": 0, **extra} for i in range(n)]


def _job(metrics=None, **fields):
    return {"verstr": "job", "status": "running", "timestamp": CREATED,
            "metrics": metrics or {}, "params": {}, **fields}


def _summary(job, rows=None):
    return job_summary(job, [Tally.of(_rows(3) if rows is None else rows, SPEC)], SPEC, T0)


def test_progress_names_its_source():
    assert _summary(_job({"progress": 1, "progress_total": 4}))["progress_source"] == "declared"
    assert _summary(_job())["progress_source"] == "runs"


def test_when_is_the_subtrees_first_start_labelled_started():
    summary = _summary(_job(started_at=HOUR_AGO), _rows(2, started_at=TWO_HOURS_AGO))
    assert (summary["when_at"], summary["when_source"]) == (TWO_HOURS_AGO, "started")


def test_when_is_the_outer_runs_own_start_before_any_inner_run_starts():
    summary = _summary(_job(started_at=HOUR_AGO))
    assert (summary["when_at"], summary["when_source"]) == (HOUR_AGO, "started")


def test_a_job_that_never_started_shows_its_creation_labelled_created():
    summary = _summary(_job())
    assert (summary["when_at"], summary["when_source"]) == (CREATED, "created")


def test_job_started_sorts_by_the_when_time():
    assert JOB_SORTS["job:started"] == "when_at"


def _rated(verstr, rate):
    declared = None if rate is None else {"done": 1, "total": 2, "unit": None,
                                          "rate_per_min": rate}
    return {"verstr": verstr, "declared_progress": declared, "throughput_per_min": 9 - (rate or 0)}


RATED = {s["verstr"]: s for s in (_rated("a", 1.0), _rated("b", None), _rated("c", 3.0))}


def _order(sort, order=None):
    rows = [{"verstr": v} for v in ("a", "b", "c")]
    return [r["verstr"] for r in job_sorted(rows, RATED, sort, order, {})]


def test_job_rate_sorts_by_the_declared_rate_jobs_without_one_last():
    assert _order("job:rate") == ["c", "a", "b"]
    assert _order("job:rate", "asc") == ["a", "c", "b"]


def test_job_throughput_sorts_by_the_runs_throughput_declared_or_not():
    assert _order("job:throughput") == ["b", "a", "c"]


def test_the_progress_and_eta_gauges_carry_the_source():
    summary = _summary(_job({"progress": 1, "progress_total": 4}))
    samples = {(name, labels.get("source")) for name, labels, _ in _job_samples({}, summary)}
    assert ("vmn_job_progress", "declared") in samples
    assert ("vmn_job_eta_seconds", "declared") in samples
    runs = {(n, labels.get("source")) for n, labels, _ in _job_samples({}, _summary(_job()))}
    assert ("vmn_job_progress", "runs") in runs
    assert all("source" not in labels for n, labels, _ in _job_samples({}, summary)
               if n == "vmn_job_runs")
