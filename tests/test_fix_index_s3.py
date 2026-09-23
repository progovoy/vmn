"""ExperimentIndex over pure S3: a poll costs a LIST plus what actually changed."""
import collections

import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from version_stamp.cli.snapshot import S3SnapshotStorage  # noqa: E402
from version_stamp.core.experiment_index import (  # noqa: E402
    ExperimentIndex,
    direct_rows,
)

APP = "root/svc"
BUCKET = "vmn-bucket"


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _storage():
    storage = S3SnapshotStorage(BUCKET, prefix="exps")
    calls = collections.Counter()
    storage._s3.meta.events.register(
        "before-call.s3", lambda event_name, **kw: calls.update([event_name.split(".")[-1]])
    )
    return storage, calls


def _seed(storage, n=3):
    verstrs = []
    for i in range(n):
        v = f"0.0.1-dev.abc.r{i}"
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        storage.append_log_entry(APP, v, "w0", {
            "timestamp": "2026-01-01T00:01:00Z", "type": "metrics", "values": {"loss": i + 0.5},
        })
        storage.save_file(APP, v, "run_state.yml", "state: running\nexit_code: null\n")
        verstrs.append(v)
    return verstrs


def _refresh(index, calls):
    calls.clear()
    index.refresh()
    return dict(calls)


def test_s3_rows_match_and_an_idle_poll_is_one_listing(s3):
    storage, calls = _storage()
    _seed(storage)
    index = ExperimentIndex(storage, APP)
    index.refresh()
    assert (index.rows(), index.run_states()) == direct_rows(storage, APP)

    assert _refresh(index, calls) == {"ListObjectsV2": 1}


def test_s3_append_is_one_ranged_get(s3, monkeypatch):
    storage, calls = _storage()
    verstrs = _seed(storage)
    index = ExperimentIndex(storage, APP)
    index.refresh()

    ranges = []
    real_get = storage._s3.get_object

    def get_object(**kwargs):
        ranges.append(kwargs.get("Range"))
        return real_get(**kwargs)

    storage.append_log_entry(APP, verstrs[1], "w0", {
        "timestamp": "2026-01-01T00:02:00Z", "type": "metrics", "values": {"loss": 0.01},
    })
    monkeypatch.setattr(storage._s3, "get_object", get_object)
    assert _refresh(index, calls) == {"ListObjectsV2": 1, "GetObject": 1}
    assert len(ranges) == 1 and ranges[0].startswith("bytes=")
    assert index.rows()[1]["metrics"]["loss"] == 0.01


def test_s3_new_segment_is_read_alone(s3):
    storage, calls = _storage()
    verstrs = _seed(storage)
    index = ExperimentIndex(storage, APP)
    index.refresh()

    storage.save_file(APP, verstrs[0], "log.w0@000001.jsonl",
                      '{"timestamp": "2026-01-01T00:03:00Z", "type": "metrics", "values": {"acc": 1}}\n')
    assert _refresh(index, calls) == {"ListObjectsV2": 1, "GetObject": 1}
    assert index.rows()[0]["metrics"]["acc"] == 1
    assert (index.rows(), index.run_states()) == direct_rows(storage, APP)


def test_s3_same_size_rewrite_in_the_same_second_is_seen(s3):
    storage, calls = _storage()
    verstrs = _seed(storage)
    index = ExperimentIndex(storage, APP)
    index.refresh()

    # Same byte length, same LastModified second: only the ETag tells them apart.
    storage.save_file(APP, verstrs[2], "run_state.yml", "state: running\nexit_code: nope\n"[:31])
    storage.save_file(APP, verstrs[2], "run_state.yml", "state: finish\nexit_code: 7\n".ljust(31))
    assert _refresh(index, calls) == {"ListObjectsV2": 1, "GetObject": 1}
    assert index.run_states()[verstrs[2]]["exit_code"] == 7
