"""The index folds a stuck run's hundreds of log and metric segments with
their reads in flight together (bounded), not one round trip after another —
and folds them exactly as a serial read would, a failed read still raising.
A small metric segment costs one read, not a prefix and a header per block."""
import json
import threading

import pytest

from vmn_exp.core import series_reader
from vmn_exp.core.index_logs import update_logs
from vmn_exp.core.index_record import new_record
from vmn_exp.core.logfiles import log_object_name
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import stream_name

APP, V = "app", "v1"
T0 = 1_700_000_000_000_000
N = 12


def _log_line(i):
    return json.dumps({"type": "params", "values": {f"p{i}": i},
                       "timestamp": f"2026-01-01T00:00:{i:02d}Z"}) + "\n"


def _files(n):
    files = {log_object_name("w", i + 1): _log_line(i).encode() for i in range(n)}
    for i in range(n):
        files[stream_name("w", i + 1)] = b"".join(
            encode_block({"loss": Columns([2 * i + k], [T0 + 2 * i + k], [float(i)])})
            for k in range(2))
    return files


class _Store:
    """Log and metric segments; reads optionally wait to overlap."""

    def __init__(self, n=N, overlap=True, fail=None):
        self.files, self.fail, self.overlap = _files(n), fail, overlap
        self.lock = threading.Lock()
        self.active = self.peak = self.reads = 0
        self.overlapped = threading.Event()

    def sigs(self):
        return {name: [len(data), 0.0, "e"] for name, data in self.files.items()}

    def metric_objects(self, app_name, verstr):
        return {"w": [(n, len(d)) for n, d in self.files.items() if n.endswith(".vms")]}

    def _read(self, name, offset, length):
        with self.lock:
            self.active += 1
            self.reads += 1
            self.peak = max(self.peak, self.active)
            if self.active >= 2:
                self.overlapped.set()
        try:
            if self.overlap:
                self.overlapped.wait(timeout=0.5)
            if name == self.fail:
                raise OSError("transport error")
            data = self.files.get(name)
            return None if data is None else data[offset:offset + length]
        finally:
            with self.lock:
                self.active -= 1

    def read_range(self, app_name, verstr, name, offset, length):
        return self._read(name, offset, length)

    def read_file_from(self, app_name, verstr, name, offset):
        return self._read(name, offset, 1 << 30)


def _fold(store):
    record = new_record()
    update_logs(record, store, store, APP, V, store.sigs())
    return record


def test_segment_reads_overlap_and_fold_as_a_serial_read_does():
    store, serial = _Store(), _Store(overlap=False)
    folded = _fold(store)
    assert store.peak >= 2
    assert folded["fold"] == _fold(serial)["fold"]
    assert folded["counts"] == {"w": N}


def test_segment_reads_are_bounded():
    store = _Store(n=4 * series_reader.SEGMENT_READ_WORKERS)
    _fold(store)
    assert 2 <= store.peak <= series_reader.SEGMENT_READ_WORKERS


def test_a_small_metric_segment_costs_one_read():
    store = _Store(overlap=False)
    _fold(store)
    assert store.reads == 2 * N  # one per log segment, one per metric segment


@pytest.mark.parametrize("fail", [stream_name("w", 5), log_object_name("w", 5)])
def test_a_failed_segment_read_raises(fail):
    with pytest.raises(OSError):
        _fold(_Store(fail=fail))
