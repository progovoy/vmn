"""``POST .../series`` over many live runs on S3, re-asked on every poll of a
Compare or outer-run chart: a run's segments are read once (the segment
cache), its ``.vmx`` — a compaction's or its owner's live rollup — costs
its footer and the LOD slices the thinned series needs, read once too; a
repeated poll costs a metadata read per run and what changed since."""
import tempfile

import pytest
from s3_helpers import meta, mocked_bucket, record_calls, s3_storage
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_compact import writer_columns
from vmn_exp.core.metric_files import stream_writer_and_seq
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.ui.readers import segment_cache
from vmn_exp.ui.routes_series import batch_series

APP, S = "app", "w~o1"
RUNS, SEGMENTS, POINTS = 20, 200, 50
T0 = 1_767_225_600_000_001
VERSTRS = [f"1.0.0-dev.r{i:02d}" for i in range(RUNS)]


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(segment_cache, "_SEGMENTS", segment_cache.SegmentCache())
    with mocked_bucket(monkeypatch):
        yield s3_storage()


def _segment(storage, v, seq):
    steps = list(range(seq * POINTS, (seq + 1) * POINTS))
    block = encode_block({
        "loss": Columns(steps, [T0 + s for s in steps], [1 / (s + 1) for s in steps]),
        "acc": Columns(steps, [T0 + s for s in steps], [s / 1e4 for s in steps]),
    })
    storage.put_metric_segment(APP, v, S, seq, block)


def _run(storage, v, segments=SEGMENTS):
    storage.save(APP, v, meta(v), {})
    line = b'{"type": "params", "params": {"lr": 0.1}, "timestamp": "2026-01-01T00:00:00Z"}\n'
    assert storage.create_log_segment(APP, v, S, 0, line)
    for seq in range(segments):
        _segment(storage, v, seq)


def _roll_up(storage, v, covers):
    objects = [(n, size) for n, size in storage.metric_objects(APP, v)[S]
               if stream_writer_and_seq(n)[1] <= covers]
    with tempfile.NamedTemporaryFile(suffix=".vmx") as f:
        f.write(build_index(S, writer_columns(storage, APP, v, objects)))
        f.flush()
        assert storage.put_indexed(APP, v, S, f.name, covers=covers)


def _post(storage):
    return batch_series(storage, APP, VERSTRS, ["loss"], 200)


def _gets(calls):
    return sum(op == "GetObject" for op, _ in calls)


def test_raw_segments_are_read_once_across_polls(s3):
    for v in VERSTRS:
        _run(s3, v)
    first = _post(s3)
    for v in VERSTRS:
        _segment(s3, v, SEGMENTS)

    calls = record_calls(s3._s3)
    again = _post(s3)

    assert _gets(calls) <= RUNS * (1 + 1)  # metadata.yml + the new segment
    assert len(again["series"][VERSTRS[0]]["loss"]) <= 200
    assert again["series_total"][VERSTRS[0]]["loss"] == first["series_total"][VERSTRS[0]]["loss"] + POINTS


def test_rolled_up_runs_cost_their_footer_and_lod_once(s3):
    for v in VERSTRS:
        _run(s3, v)
        _roll_up(s3, v, SEGMENTS - 4)

    calls = record_calls(s3._s3)
    first = _post(s3)
    first_gets = _gets(calls)
    calls.clear()
    again = _post(s3)

    # metadata, log, the .vmx footer + one LOD slice, the 3 segments after it
    assert first_gets <= RUNS * (1 + 1 + 2 + 3)
    assert _gets(calls) <= RUNS  # metadata.yml alone
    assert again == first
    assert len(first["series"][VERSTRS[0]]["loss"]) <= 200
    assert first["series_total"][VERSTRS[0]]["loss"] == SEGMENTS * POINTS
