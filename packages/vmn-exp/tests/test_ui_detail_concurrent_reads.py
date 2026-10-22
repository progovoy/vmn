"""The run detail's independent store reads overlap (a 30 ms-latency S3
store paid each one in turn: 0.76 s for one outer run), and the payload stays
exactly what the sequential reader built (``golden/run_detail.json``)."""
import json
import os
import threading
import time

import pytest
import detail_fixture as fx

from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.readers.experiment_detail import experiment_detail

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "run_detail.json")
LATENCY = 0.03
_READS = ("load_file", "load_metadata", "list_artifacts", "record_files", "metric_objects",
          "log_sizes", "load_logs_by_writer", "read_file_from", "read_range", "list_files")


class _SlowStore(LocalSnapshotStorage):
    """Every read waits a round trip; the peak of reads in flight is kept."""

    def __init__(self, *args):
        super().__init__(*args)
        self.lock = threading.Lock()
        self.in_flight = self.peak = self.reads = 0


def _slow(name):
    real = getattr(LocalSnapshotStorage, name)

    def read(self, *args, **kwargs):
        with self.lock:
            self.in_flight += 1
            self.reads += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            time.sleep(LATENCY)
            return real(self, *args, **kwargs)
        finally:
            with self.lock:
                self.in_flight -= 1

    return read


for _name in _READS:
    setattr(_SlowStore, _name, _slow(_name))


@pytest.fixture
def root(tmp_path):
    fx.build(str(tmp_path / "root"))
    return str(tmp_path / "root")


def _golden():
    with open(GOLDEN) as f:
        return json.load(f)


@pytest.mark.parametrize("verstr", fx.VERSTRS)
def test_the_payload_matches_the_sequential_readers(root, verstr):
    storage = LocalSnapshotStorage(root, area="runs")
    detail, err = experiment_detail(storage, fx.APP, verstr, edges=fx.edges)

    assert err is None
    assert json.loads(fx.canonical(detail)) == _golden()[verstr]


@pytest.mark.parametrize("verstr", [fx.OUTER, fx.FAILED])
def test_independent_reads_overlap_and_the_payload_is_unchanged(root, verstr):
    storage = _SlowStore(root, "runs")
    started = time.monotonic()
    detail, err = experiment_detail(storage, fx.APP, verstr, edges=fx.edges)
    elapsed = time.monotonic() - started

    assert err is None
    assert json.loads(fx.canonical(detail)) == _golden()[verstr]
    assert storage.peak > 1
    # Far fewer sequential round trips than reads.
    assert elapsed < (storage.reads * LATENCY) * 0.6, (elapsed, storage.reads)
