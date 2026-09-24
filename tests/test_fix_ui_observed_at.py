"""The leaderboard judges liveness on the store's clock when the index knows
when run_state.yml was last written, so a writer whose clock is behind is not
reported stuck."""
import datetime

from version_stamp.core.experiment_index_snapshot import IndexSnapshot
from version_stamp.core.experiment_log import experiment_row
from version_stamp.ui import leaderboard_cache as lb

APP = "app"


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _skewed_snapshot(observed):
    now = datetime.datetime.now(datetime.timezone.utc)
    writer_clock = now - datetime.timedelta(hours=1)
    verstr = "1.0.0-dev.r0001"
    row = experiment_row(1, {"verstr": verstr, "timestamp": _iso(writer_clock)}, [])
    state = {"state": "running", "pid": 1, "host": "h", "started_at": _iso(writer_clock),
             "heartbeat": _iso(writer_clock), "heartbeat_interval_sec": 30}
    seen = {verstr: now} if observed else {}
    return IndexSnapshot.build(APP, 1, [row], {verstr: state}, observed_at=seen)


def test_a_fresh_store_write_keeps_a_skewed_writer_running():
    page = lb.LeaderboardCache(bucket_sec=2).page(_skewed_snapshot(True), {}, limit=10)
    assert page["rows"][0]["status"] == "running"


def test_without_a_store_time_the_old_rule_applies():
    page = lb.LeaderboardCache(bucket_sec=2).page(_skewed_snapshot(False), {}, limit=10)
    assert page["rows"][0]["status"] == "stuck"
