"""``vmn-exp compact`` / ``vmn-exp watch --compact`` also merge a dead run's
log segments: a stuck run synced one per 30 s and never compacted, and every
cold index load paid a GET for each. A running run's segments are left alone
(its writer still appends)."""
import datetime
import json
import time

import pytest
import yaml

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.cli.compact import DEAD, compact_runs, runs_with_status  # noqa: E402
from vmn_exp.core.status import RUN_STATE_FILE  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "myapp"
BUCKET = "vmn-bucket"
SEGMENTS = 4


@pytest.fixture
def s3(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("VMN_EXP_MIN_STALE_SEC", "1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield S3SnapshotStorage(BUCKET, prefix="exps")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(storage, verstr, exit_code, interval=30):
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    for seq in range(1, SEGMENTS + 1):
        line = json.dumps({"type": "tags", "set": {f"t{seq}": "x"},
                           "timestamp": "2026-01-01T00:00:00Z"}) + "\n"
        storage.create_log_segment(APP, verstr, "w", seq, line.encode())
    state = {"state": "finished" if exit_code is not None else "running", "pid": 1,
             "host": "h", "started_at": _now(), "heartbeat": _now(),
             "heartbeat_interval_sec": interval, "exit_code": exit_code}
    storage.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(state, sort_keys=False))


def _log_objects(storage, verstr):
    return storage.log_object_groups(APP, verstr)["w"]


def test_compact_merges_dead_runs_log_segments_and_leaves_a_running_one(s3, capfd):
    _run(s3, "0.0.1", exit_code=1)
    _run(s3, "0.0.2", exit_code=None, interval=0.1)  # stuck once its window passes
    time.sleep(1.5)
    _run(s3, "0.0.3", exit_code=None)
    dead = runs_with_status(s3, APP, DEAD)
    assert dead == ["0.0.1", "0.0.2"]

    assert compact_runs(s3, APP, dead) == 0

    for verstr in dead:
        assert len(_log_objects(s3, verstr)) == 1
        assert len(s3.load_logs_by_writer(APP, verstr)["w"]) == SEGMENTS
    assert len(_log_objects(s3, "0.0.3")) == SEGMENTS
    assert "0.0.1 compacted (1 log)" in capfd.readouterr().out
