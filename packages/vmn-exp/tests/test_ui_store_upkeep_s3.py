"""Store upkeep on S3 decides from listings: a dead run whose listing shows
one log object per stream and its metrics on a ``.vmx`` is never read again,
in this process or the next one."""
import datetime
import json

import pytest
import yaml

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.core import index as experiment_index  # noqa: E402
from vmn_exp.core.metric_stream import MetricWriter  # noqa: E402
from vmn_exp.core.status import RUN_STATE_FILE  # noqa: E402
from vmn_exp.core.writer import create_run  # noqa: E402
from vmn_exp.storage import s3_stats  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402
from vmn_exp.ui.store_upkeep import AppUpkeep  # noqa: E402

APP = "my_app"
CODE = "0.0.1-dev.abc.def"
BUCKET = "vmn-bucket"
MISSING = ("NoSuchKey", "404", "NotFound")


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield S3SnapshotStorage(BUCKET, prefix="vmn/runs")


@pytest.fixture
def calls():
    seen = []
    s3_stats.add_listener(seen.append)
    yield seen
    s3_stats.remove_listener(seen.append)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dead_run(storage, segments=3):
    """A failed run with *segments* log segments and as many metric segments."""
    verstr = create_run(storage, APP, CODE, {"timestamp": _now()}, {})
    for seq in range(1, segments + 1):
        line = json.dumps({"type": "params", "timestamp": _now(), "params": {f"p{seq}": seq}})
        storage.put_log_segment(APP, verstr, "w", seq, (line + "\n").encode())
        w = MetricWriter(storage, APP, verstr, "w")
        w.add("loss", 1.0 / seq, step=seq)
        w.flush()
    state = {"state": "finished", "pid": 1, "host": "h", "started_at": _now(),
             "heartbeat": _now(), "heartbeat_interval_sec": 30, "exit_code": 1}
    storage.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(state, sort_keys=False))
    return verstr


def _log_gets(calls):
    return [c for c in calls if c.operation == "GetObject" and "/log/" in c.key]


def _misses(calls):
    return [c for c in calls if c.error in MISSING]


def test_compacted_dead_runs_are_not_read_again_in_this_or_the_next_process(storage, calls):
    for _ in range(3):
        _dead_run(storage)
    snap = experiment_index.indexed_snapshot(storage, APP, wait=True)
    assert AppUpkeep(storage, APP).run(snap)["compacted"] == 3

    calls.clear()
    counts = AppUpkeep(storage, APP).run(snap)  # a restarted server

    assert _log_gets(calls) == []
    assert _misses(calls) == []
    assert counts == {"marked": 0, "compacted": 0, "failed": 0}


def test_a_restarted_upkeep_lists_each_compacted_run_at_most_twice(storage, calls):
    verstrs = [_dead_run(storage) for _ in range(2)]
    snap = experiment_index.indexed_snapshot(storage, APP, wait=True)
    AppUpkeep(storage, APP).run(snap)

    calls.clear()
    AppUpkeep(storage, APP).run(snap)

    reads = [c for c in calls if c.operation in ("GetObject", "HeadObject")]
    assert reads == []
    for verstr in verstrs:
        assert len([c for c in calls if f"/{verstr}/" in c.key]) <= 2
