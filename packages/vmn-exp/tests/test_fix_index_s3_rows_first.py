"""A cold remote load publishes a run's row before reading its hundreds of
segments: the newest records of a store are usually its stuck runs (the
latest launch), each with a log and a metric segment per 30 s sync, so
reading them whole first kept the board empty for minutes. A row comes from
metadata.yml, run_state.yml and each stream's first log object; the rest of
its log and its metric segments are folded afterwards, into the same row."""
import json
import threading
import time

import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.core.metric_block import encode_block  # noqa: E402
from vmn_exp.core.metric_columns import Columns  # noqa: E402
from vmn_exp.core.status import FAILED, derive_status  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "myapp"
BUCKET = "vmn-bucket"
N, SEGMENTS = 6, 8
T0 = 1_700_000_000_000_000


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _storage():
    return S3SnapshotStorage(BUCKET, prefix="exps")


def _line(entry):
    return (json.dumps(entry) + "\n").encode()


def _seed(storage):
    for i in range(N):
        v = f"0.0.{i}"
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
        storage.save_file(APP, v, "run_state.yml", "state: failed\nexit_code: 1\n")
        storage.create_log_segment(APP, v, "w", 1, _line(
            {"type": "params", "params": {"lr": 0.1}, "timestamp": "2026-01-01T00:00:00Z"}))
        for seq in range(2, SEGMENTS + 1):
            storage.create_log_segment(APP, v, "w", seq, _line(
                {"type": "tags", "set": {f"t{seq}": "x"}, "timestamp": "2026-01-01T00:01:00Z"}))
        for seq in range(1, SEGMENTS + 1):
            storage.create_metric_segment(APP, v, "w", seq, encode_block(
                {"loss": Columns([seq], [T0 + seq], [float(seq)])}))


def _hold_segment_reads(storage, release):
    """Reads past each stream's first object wait for *release*; the event
    returned is set when one gave up waiting."""
    read_range, read_from = storage.read_range, storage.read_file_from
    gave_up = threading.Event()

    def hold():
        if not release.wait(5):
            gave_up.set()

    def held_range(app_name, verstr, name, offset, length):
        hold()
        return read_range(app_name, verstr, name, offset, length)

    def held_from(app_name, verstr, name, offset):
        if "@000001" not in name:
            hold()
        return read_from(app_name, verstr, name, offset)

    storage.read_range, storage.read_file_from = held_range, held_from
    return gave_up


def _rows_once(index, n, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = index.snapshot().rows
        if len(rows) >= n:
            return rows
        time.sleep(0.01)
    raise AssertionError(f"never saw {n} rows")


def test_a_cold_load_publishes_rows_before_reading_segments(s3, tmp_path):
    _seed(_storage())
    storage, release = _storage(), threading.Event()
    gave_up = _hold_segment_reads(storage, release)
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))
    try:
        rows = _rows_once(index, N)
        assert not gave_up.is_set()
        assert all(r["params"] == {"lr": 0.1} for r in rows)
        states = index.snapshot().run_states.values()
        assert [derive_status(s) for s in states] == [FAILED] * N
    finally:
        release.set()
    index.wait_revalidated(30)

    rows = index.snapshot().rows
    assert all(r["metrics"]["loss"] == float(SEGMENTS) for r in rows)
    assert all(len(r["tags"]) == SEGMENTS - 1 for r in rows)
