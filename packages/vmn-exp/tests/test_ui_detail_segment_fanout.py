"""A run page's first open of a long-stuck run on S3 reads every log and
metric segment it ever shipped, one GET each (2,000 segments at 30 ms: 9 s
behind the run page's skeleton, ten in flight). Those reads are
latency-bound, so a request reads them as wide as the request lane lets it
(:data:`vmn_exp.storage.fanout.REQUEST_WORKERS`), not
:data:`~vmn_exp.storage.s3_base.S3_WORKERS` at a time."""
import json
import threading
import time

import pytest
from s3_helpers import meta, mocked_bucket, s3_storage
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.storage import fanout
from vmn_exp.storage.s3_base import S3_WORKERS
from vmn_exp.ui.readers import experiment_detail
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP, V, S = "app", "1.0.0-dev.a", "w~o1"
T0 = 1_767_225_600_000_000
SEGMENTS = 120
LATENCY = 0.02


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(experiment_detail, "_PARSED", ParsedLogs())
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save(APP, V, meta(V), {})
        yield storage


def _stuck_run(storage):
    for seq in range(SEGMENTS):
        entry = {"type": "note", "note": f"sync {seq}",
                 "timestamp": f"2026-01-01T00:00:00.{seq:06d}Z"}
        storage.create_log_segment(APP, V, S, seq, (json.dumps(entry) + "\n").encode())
    for seq in range(SEGMENTS):
        writer = MetricWriter(storage, APP, V, S)
        writer.add("cv0.loss", 1 / (seq + 1), step=seq, ts_us=T0 + seq)
        writer.flush()


class _InFlightGets:
    """The peak of GETs in flight, each held a round trip."""

    def __init__(self, client):
        self.now = self.peak = 0
        self._lock = threading.Lock()
        client.meta.events.register("before-call.s3.GetObject", self._started)
        client.meta.events.register("after-call.s3.GetObject", self._done)

    def _started(self, **_):
        with self._lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        time.sleep(LATENCY)

    def _done(self, **_):
        with self._lock:
            self.now -= 1


def test_a_cold_detail_reads_its_segments_as_wide_as_the_request_lane(s3):
    _stuck_run(s3)
    gets = _InFlightGets(s3._s3)

    with fanout.serving_request():
        detail, err = experiment_detail.experiment_detail(
            s3, APP, V, edges=lambda storage, app: {V: None})

    assert err is None
    assert detail["log_total"] == 2 * SEGMENTS
    assert len(detail["series"]["cv0.loss"]) == SEGMENTS
    assert gets.peak > S3_WORKERS
    assert gets.peak >= fanout.REQUEST_WORKERS - 4  # the detail's other reads overlap
