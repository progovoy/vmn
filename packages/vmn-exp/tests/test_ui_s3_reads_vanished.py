"""A run's detail and series readers list its segments, then GET them; a
compaction (the owner's live rollup, store upkeep) may merge and delete them
in between. The listing is then stale: the first object found missing costs
one fresh listing and its reads — never a failure, nor a 404 per segment."""
import json

import pytest
from s3_helpers import meta, mocked_bucket, op_counts, record_calls, s3_storage
from vmn_exp.core.log import load_log, metric_series
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.ui.readers import experiment_detail, segment_cache
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP, V = "app", "1.0.0-dev.a"
S = "w~o1"
T0 = 1_767_225_600_000_000


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(segment_cache, "_SEGMENTS", segment_cache.SegmentCache())
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save(APP, V, meta(V), {})
        yield storage


def _segments(storage, start, stop):
    for seq in range(start, stop):
        line = json.dumps({"timestamp": f"2026-01-01T00:00:00.{seq:06d}Z", "type": "note",
                           "note": f"n{seq}"}) + "\n"
        assert storage.create_log_segment(APP, V, S, seq, line.encode())


def _compact_after_listing(storage, monkeypatch):
    """The next listing of *storage* is followed by a compaction of its log:
    ``[calls made from then on]``."""
    real, after = storage.stream_files, []

    def list_then_compact(app_name, verstr):
        files = real(app_name, verstr)
        if not after:
            assert storage.compact_log_segments(APP, V, S)
            after.append(record_calls(storage._s3))
        return files

    monkeypatch.setattr(storage, "stream_files", list_then_compact)
    return after


def _missed(calls, storage):
    """GETs of the log segments the compaction deleted."""
    gone = f"{storage._record_prefix(APP, V)}/log/{S}"
    return [p for op, p in calls if op == "GetObject" and p["Key"].startswith(gone)
            and "-" not in p["Key"][len(gone):]]


@pytest.mark.parametrize("warm", [False, True])
def test_the_detail_log_lists_again_once(s3, monkeypatch, warm):
    _segments(s3, 0, 20)
    cache = ParsedLogs()
    if warm:
        cache.get(s3, APP, V, load_log)
        _segments(s3, 20, 30)
    after = _compact_after_listing(s3, monkeypatch)

    snap = cache.get(s3, APP, V, load_log)

    ops = op_counts(after[0])
    assert ops["GetObject"] <= 2  # the missed probe, then the merged object
    assert ops["ListObjectsV2"] == 2  # one fresh listing: log/ and metrics/
    full = load_log(s3, APP, V)
    assert snap.log() == full and len(full) == (30 if warm else 20)
    assert cache.get(s3, APP, V, load_log) is snap  # kept, under the fresh listing


def test_run_series_lists_again_once(s3, monkeypatch):
    _segments(s3, 0, 20)
    w = MetricWriter(s3, APP, V, S)
    for step in range(5):
        w.add("loss", 1 / (step + 1), step=step, ts_us=T0 + step)
    w.flush()
    after = _compact_after_listing(s3, monkeypatch)

    got = experiment_detail.run_series(s3, APP, V)

    assert len(_missed(after[0], s3)) <= 1
    assert got[0] == {"loss": metric_series(load_log(s3, APP, V))["loss"]}
