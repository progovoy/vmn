"""A never-compacted writer's ``.vms`` segments are read concurrently.

A stuck run on S3 has one segment per 30s sync — hundreds or thousands — and a
serial ranged GET each made Compare take minutes. Reads overlap (bounded), the
blocks still come back in segment order and a failed read still raises.
"""
import threading

import pytest

from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import stream_name
from vmn_exp.core.series_reader import SeriesReader

APP, V = "app", "v1"
N_SEGMENTS = 12
T0 = 1_700_000_000_000_000


class _SegmentStore:
    """One block per segment: segment *i* holds step *i* of ``loss``."""

    def __init__(self, n=N_SEGMENTS, fail_at=None):
        self.data = {
            stream_name("w", i): encode_block({"loss": Columns([i], [T0 + i], [float(i)])})
            for i in range(n)
        }
        self.fail_at = fail_at
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.overlapped = threading.Event()

    def metric_objects(self, app_name, verstr):
        return {"w": [(name, len(data)) for name, data in self.data.items()]}

    def read_range(self, app_name, verstr, name, offset, length):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= 2:
                self.overlapped.set()
        try:
            self.overlapped.wait(timeout=0.5)
            if self.fail_at is not None and name == stream_name("w", self.fail_at):
                raise OSError("transport error")
            return self.data[name][offset:offset + length]
        finally:
            with self.lock:
                self.active -= 1


def test_segment_reads_overlap_and_keep_order():
    store = _SegmentStore()
    reader = SeriesReader.from_storage(store, APP, V, rewinds=())
    steps = [p["step"] for p in reader.series("loss")]
    assert steps == list(range(N_SEGMENTS))
    assert store.peak >= 2


def test_segment_reads_are_bounded():
    from vmn_exp.core import series_reader

    store = _SegmentStore(n=4 * series_reader.SEGMENT_READ_WORKERS)
    SeriesReader.from_storage(store, APP, V, rewinds=()).keys()
    assert 2 <= store.peak <= series_reader.SEGMENT_READ_WORKERS


def test_a_failed_segment_read_raises():
    store = _SegmentStore(fail_at=5)
    with pytest.raises(OSError):
        SeriesReader.from_storage(store, APP, V, rewinds=()).keys()
