"""Plan 23 S3: a job's timeline — runs started, succeeded and failed per
minute (per 10 minutes once the job spans more than a day), from the
tallies, exact under removal and across parts."""
import datetime

from leaderboard_fleet import T0, iso
from vmn_exp.ui.job_rollup_payload import job_payload
from vmn_exp.ui.job_tally import RollupSpec, Tally

SPEC = RollupSpec({})


def _row(n, status, start_ago, end_ago=None):
    row = {"verstr": f"v{n:03d}", "parent": "job", "status": status, "metrics": {},
           "started_at": iso(T0 - datetime.timedelta(seconds=start_ago))}
    if end_ago is not None:
        row["finished_at"] = iso(T0 - datetime.timedelta(seconds=end_ago))
    return row


def _timeline(parts):
    return job_payload({"verstr": "job", "params": {}}, parts, SPEC, T0)["timeline"]


def _minute_t(ago):
    return int((T0 - datetime.timedelta(seconds=ago)).timestamp() // 60) * 60


def test_runs_are_counted_per_minute_by_start_and_outcome():
    rows = [_row(0, "succeeded", 300, 120), _row(1, "failed", 300, 60),
            _row(2, "running", 60), _row(3, "stuck", 600, 500)]
    got = _timeline([Tally.of(rows, SPEC)])
    assert got["bucket_sec"] == 60
    assert got["buckets"] == [
        {"t": _minute_t(600), "started": 1, "succeeded": 0, "failed": 0},
        {"t": _minute_t(300), "started": 2, "succeeded": 0, "failed": 0},
        {"t": _minute_t(120), "started": 0, "succeeded": 1, "failed": 0},
        {"t": _minute_t(60), "started": 1, "succeeded": 0, "failed": 1},
    ]
    assert got["start"] == _minute_t(600)


def test_a_job_spanning_more_than_a_day_is_bucketed_per_ten_minutes():
    day = 24 * 3600
    rows = [_row(0, "succeeded", 2 * day, 2 * day - 30), _row(1, "succeeded", 120, 60)]
    got = _timeline([Tally.of(rows, SPEC)])
    assert got["bucket_sec"] == 600
    assert [b["t"] % 600 for b in got["buckets"]] == [0] * len(got["buckets"])
    assert sum(b["started"] for b in got["buckets"]) == 2
    assert sum(b["succeeded"] for b in got["buckets"]) == 2


def test_removing_a_run_takes_it_out_of_its_buckets():
    rows = [_row(i, "succeeded", 300 + i, 100) for i in range(3)]
    tally = Tally.of(rows, SPEC)
    tally.add(rows[0], SPEC, by=-1)
    assert _timeline([tally]) == _timeline([Tally.of(rows[1:], SPEC)])


def test_parts_add_up_like_one_tally():
    rows = [_row(i, "failed" if i % 3 else "succeeded", 60 * i + 200, 60 * i) for i in range(20)]
    assert _timeline([Tally.of(rows[:8], SPEC), Tally.of(rows[8:], SPEC)]) == _timeline(
        [Tally.of(rows, SPEC)])


def test_an_empty_job_has_no_buckets():
    assert _timeline([]) == {"bucket_sec": 60, "start": None, "buckets": []}
