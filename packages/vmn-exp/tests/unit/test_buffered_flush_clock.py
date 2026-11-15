"""A direct-to-bucket log buffer times its flush interval on the clock it is
handed (plan 44 G10)."""
import pytest
from deferred_ship_fakes import FakeBucket
from fakes.clock import FakeClock

from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.open import open_storage

APP, V, W = "app", "v", "w"
INTERVAL = 5


@pytest.fixture
def bucket(tmp_path):
    remote = FakeBucket(str(tmp_path / "bucket"))
    remote.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    yield remote
    buffered.close_all()


def _pod(bucket, tmp_path, clock):
    return BufferedRemoteStorage(bucket, str(tmp_path / "buffers"), area="runs",
                                 flush_interval_sec=INTERVAL, clock=clock)


def _entry(i):
    return {"timestamp": f"2026-01-01T00:00:{i:02d}Z", "type": "metrics", "values": {"x": i}}


def _block(value):
    return encode_block({"x": Columns([0], [0], [value])})


def test_log_ships_once_per_flush_interval(bucket, tmp_path):
    clock = FakeClock()
    pod = _pod(bucket, tmp_path, clock)

    pod.append_log_entry(APP, V, W, _entry(0))  # the first ships at once
    clock.advance(INTERVAL - 1)
    pod.append_log_entry(APP, V, W, _entry(1))
    assert bucket.creates == 1

    clock.advance(1)
    pod.append_log_entry(APP, V, W, _entry(2))
    assert bucket.creates == 2


def test_metric_block_ships_when_the_interval_elapsed(bucket, tmp_path):
    clock = FakeClock()
    pod = _pod(bucket, tmp_path, clock)

    pod.append_metric_block(APP, V, W, _block(1.0))
    clock.advance(INTERVAL - 1)
    pod.append_metric_block(APP, V, W, _block(2.0))
    assert bucket.creates == 1

    clock.advance(1)
    pod.append_metric_block(APP, V, W, _block(3.0))
    assert bucket.creates == 2


def test_a_storage_opened_in_another_area_keeps_the_clock(bucket, tmp_path):
    clock = FakeClock()

    other = _pod(bucket, tmp_path, clock).in_area("snapshots")

    assert other._clock is clock


def test_open_storage_with_buffer_logs_requires_a_clock():
    with pytest.raises(TypeError, match="clock"):
        open_storage("s3://bucket/prefix", area="runs", buffer_logs=True)
