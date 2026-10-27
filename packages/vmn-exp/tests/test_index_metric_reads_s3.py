"""The index reads each metric segment of an S3 run once: a live run's
refresh GETs only its new segments, a refold of its log (the owner's live log
rollup, the end-of-run log compaction) re-reads none of them, and a ``.vmx``
replacing segments the index already folded costs its footer alone."""
import os

import pytest
from s3_helpers import meta, mocked_bucket, record_calls, s3_storage
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_compact import compact_writer

APP, V = "app", "1.0.0-dev.a"
S = "w~o1"
T0 = 1_767_225_600_000_001  # not a whole second: its ISO form has digits


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save(APP, V, meta(V), {})
        storage.save_file(APP, V, "run_state.yml", "state: running\nexit_code: null\n")
        yield storage


def _segment(storage, seq):
    steps = [2 * seq, 2 * seq + 1]
    block = encode_block({
        "loss": Columns(steps, [T0 + 10 * s for s in steps], [1 / (s + 1) for s in steps]),
        "sys_cpu": Columns(None, [T0 + 10 * steps[0] + 1], [float(seq % 7)]),
    })
    storage.put_metric_segment(APP, V, S, seq, block)


def _log_segment(storage, seq):
    line = f'{{"type": "note", "note": "n{seq}", "timestamp": "2026-01-01T00:00:{seq:02d}Z"}}\n'
    assert storage.create_log_segment(APP, V, S, seq, line.encode())


def _index(tmp_path, name="i.sqlite"):
    return ExperimentIndex(s3_storage(), APP, os.path.join(tmp_path, name), full_sweep_sec=0)


def _metric_gets(calls):
    return [p["Key"] for op, p in calls if op == "GetObject" and "/metrics/" in p["Key"]]


def _log_gets(calls):
    return [p["Key"] for op, p in calls if op == "GetObject" and "/log/" in p["Key"]]


def _row(index):
    row = index.refresh().rows()[0]
    return row["metrics"], row["metric_summary"], row["last_metric_at"]


def _live_run(storage, segments=500, logs=3):
    for seq in range(segments):
        _segment(storage, seq)
    for seq in range(logs):
        _log_segment(storage, seq)


def test_a_refresh_after_three_new_segments_gets_those_three(s3, tmp_path):
    _live_run(s3)
    index = _index(tmp_path)
    index.refresh()
    for seq in range(500, 503):
        _segment(s3, seq)

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert len(_metric_gets(calls)) <= 3
    assert got == _row(_index(tmp_path, "fresh.sqlite"))


def test_a_rolled_up_log_reads_no_metric_segment_again(s3, tmp_path):
    _live_run(s3)
    index = _index(tmp_path)
    index.refresh()
    assert s3.compact_log_segments(APP, V, S)  # the owner's live log rollup

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert _metric_gets(calls) == []
    assert got == _row(_index(tmp_path, "fresh.sqlite"))


def test_a_warm_restart_keeps_what_the_metric_segments_folded_to(s3, tmp_path):
    _live_run(s3)
    _index(tmp_path).refresh()
    assert s3.compact_log_segments(APP, V, S)
    index = _index(tmp_path)  # a restart: the persisted records

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert _metric_gets(calls) == []
    assert got == _row(_index(tmp_path, "fresh.sqlite"))


def test_a_vmx_of_the_folded_segments_costs_its_footer_not_a_refold(s3, tmp_path):
    _live_run(s3)
    index = _index(tmp_path)
    index.refresh()
    assert compact_writer(s3, APP, V, S)

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert len(_metric_gets(calls)) <= 1
    assert _log_gets(calls) == []
    assert got == _row(_index(tmp_path, "fresh.sqlite"))


def _put_rollup(storage, covers):
    """A ``.vmx`` of the stream's segments up to *covers*, the later ones
    left (the owner's live rollup)."""
    import tempfile

    from vmn_exp.core.metric_compact import writer_columns
    from vmn_exp.core.metric_files import stream_writer_and_seq
    from vmn_exp.core.metric_index_file import build_index

    objects = [(n, size) for n, size in storage.metric_objects(APP, V)[S]
               if stream_writer_and_seq(n)[1] <= covers]
    data = build_index(S, writer_columns(storage, APP, V, objects))
    with tempfile.NamedTemporaryFile(suffix=".vmx") as f:
        f.write(data)
        f.flush()
        assert storage.put_indexed(APP, V, S, f.name, covers=covers)


def test_a_rollup_leaving_folded_segments_after_it_costs_its_footer(s3, tmp_path):
    _live_run(s3)
    index = _index(tmp_path)
    index.refresh()
    _put_rollup(s3, covers=495)

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert len(_metric_gets(calls)) <= 1
    assert _log_gets(calls) == []
    assert got == _row(_index(tmp_path, "fresh.sqlite"))
    for seq in range(500, 502):
        _segment(s3, seq)
    _put_rollup(s3, covers=499)
    assert s3.compact_log_segments(APP, V, S)

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert len(_metric_gets(calls)) <= 1 + 2  # the footer and the new segments
    assert got == _row(_index(tmp_path, "fresh2.sqlite"))


def test_a_vmx_holding_segments_never_folded_refolds_the_writer(s3, tmp_path):
    _live_run(s3, segments=20)
    index = _index(tmp_path)
    index.refresh()
    for seq in range(20, 25):
        _segment(s3, seq)
    assert compact_writer(s3, APP, V, S)
    _segment(s3, 25)

    calls = record_calls(index._storage._s3)
    got = _row(index)

    assert len(_metric_gets(calls)) <= 2  # the footer and the segment after it
    assert got == _row(_index(tmp_path, "fresh.sqlite"))


def test_a_first_segment_of_many_blocks_is_one_get(s3, tmp_path):
    blocks = [encode_block({"loss": Columns([i], [T0 + i], [float(i)])}) for i in range(30)]
    s3.put_metric_segment(APP, V, S, 0, b"".join(blocks))
    index = _index(tmp_path)

    calls = record_calls(index._storage._s3)
    metrics, _, _ = _row(index)

    assert metrics["loss"] == 29.0
    assert len(_metric_gets(calls)) == 1
