"""``POST .../series`` for one finished, compacted run on S3: ~1 s on a
30 ms-latency store when its reads went one after another. Its independent
reads overlap and none is made twice, so the critical path is a few round
trips — with the payload a sequential reader builds."""
import time

import pytest
import series_s3_fixture as fx
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.routes_series import batch_series

LATENCY = 0.05


@pytest.fixture
def s3(monkeypatch, tmp_path):
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        fx.compacted_run(storage, tmp_path)
        yield storage


def _trace(log):
    return "\n".join(f"{s:.3f}-{e:.3f} {op} {key}" for s, e, op, key in sorted(log.calls))


def _series(storage):
    return batch_series(storage, fx.APP, [fx.V], None, 2000)


def test_one_run_is_a_few_round_trips(s3):
    with fx.recorded_calls(s3._s3, LATENCY) as log:
        started = time.monotonic()
        _series(s3)
        elapsed = time.monotonic() - started

    trace = _trace(log)
    assert log.critical_path() <= 4, trace
    assert len(log.calls) <= 7, trace
    assert elapsed < 6 * LATENCY, trace


def test_the_payload_is_the_local_copys(s3, tmp_path):
    local = LocalSnapshotStorage(str(tmp_path / "local"), "runs")
    fx.compacted_run(local, tmp_path)

    remote = _series(s3)

    assert remote == _series(local)
    series = remote["series"][fx.V]
    assert sorted(series) == ["acc", "loss"]
    assert remote["series_total"][fx.V] == {"acc": fx.POINTS, "loss": fx.POINTS}
    assert remote["missing"] == []


def test_a_file_past_the_tail_read_reads_its_keys_concurrently(s3, monkeypatch):
    from vmn_exp.core import metric_index_reader

    monkeypatch.setattr(metric_index_reader, "TAIL_READ_BYTES", 1024)
    with fx.recorded_calls(s3._s3, LATENCY) as log:
        payload = _series(s3)

    trace = _trace(log)
    # metadata | listings, then logs | the tail, then per key: LOD | edges.
    assert log.critical_path() <= 5, trace
    assert payload["series_total"][fx.V] == {"acc": fx.POINTS, "loss": fx.POINTS}


def test_a_missing_run_is_reported_missing(s3):
    assert batch_series(s3, fx.APP, ["nope"], None, 2000)["missing"] == ["nope"]
