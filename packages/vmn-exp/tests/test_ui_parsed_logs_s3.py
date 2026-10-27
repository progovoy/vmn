"""The run-detail log cache over an S3 store: a long-lived run ships a log
segment per sync, so a page polling it must GET only the segments it has not
read yet — one listing plus the new objects — and still answer exactly what a
full read does, through compactions and out-of-order writers."""
import json

import pytest
from s3_helpers import meta, mocked_bucket, op_counts, record_calls, s3_storage
from vmn_exp.core.log import load_log, metric_series
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP, V = "app", "1.0.0-dev.a"
S, T = "w~o1", "x~o2"
T0 = 1_767_225_600_000_000


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save(APP, V, meta(V), {})
        yield storage


def _ts(i):
    return f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}.{i % 1000:06d}Z"


def _segment(storage, stream, seq, *stamps):
    lines = "".join(
        json.dumps({"timestamp": _ts(i), "type": "metrics", "step": i, "values": {"loss": i / 7}})
        + "\n"
        for i in stamps
    )
    assert storage.create_log_segment(APP, V, stream, seq, lines.encode())


def _assert_full(snap, storage):
    full = load_log(storage, APP, V)
    assert snap.log() == full
    assert snap.series() == metric_series(full)


def _gets(storage, read):
    calls = record_calls(storage._s3)
    result = read()
    return result, op_counts(calls)


def test_a_repeated_read_gets_only_the_new_segments(s3):
    for seq in range(1000):
        _segment(s3, S, seq, seq)
    cache = ParsedLogs()

    first, ops = _gets(s3, lambda: cache.get(s3, APP, V, load_log))
    assert ops["GetObject"] == 1000
    assert first.total == 1000

    for seq in range(1000, 1003):
        _segment(s3, S, seq, seq)
    snap, ops = _gets(s3, lambda: cache.get(s3, APP, V, load_log))

    assert ops["GetObject"] == 3
    # The record's log/ (two pages of 1000) and metrics/ listings.
    assert ops["ListObjectsV2"] == 3
    _assert_full(snap, s3)


def test_an_unchanged_record_costs_its_listing_only(s3):
    for seq in range(5):
        _segment(s3, S, seq, seq)
    cache = ParsedLogs()
    first = cache.get(s3, APP, V, load_log)

    again, ops = _gets(s3, lambda: cache.get(s3, APP, V, load_log))

    assert again is first
    assert ops["GetObject"] == 0


def test_writers_shipping_out_of_order_still_cost_only_their_new_segments(s3):
    _segment(s3, S, 0, 10, 20)
    _segment(s3, T, 0, 15, 25)
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    _segment(s3, T, 1, 30)
    _segment(s3, S, 1, 21, 40)  # 21 sorts before the other writer's 25 and 30
    snap, ops = _gets(s3, lambda: cache.get(s3, APP, V, load_log))

    assert ops["GetObject"] == 2
    _assert_full(snap, s3)


def test_a_compaction_between_reads_gives_the_full_result(s3):
    for seq in range(20):
        _segment(s3, S, seq, seq)
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    assert s3.compact_log_segments(APP, V, S)
    _segment(s3, S, 20, 20)
    snap = cache.get(s3, APP, V, load_log)

    assert snap.total == 21
    _assert_full(snap, s3)


def test_a_live_rollup_of_segments_read_already_costs_no_read(s3):
    for seq in range(20):
        _segment(s3, S, seq, seq)
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    assert s3.compact_log_segments(APP, V, S)  # their bytes, concatenated
    _segment(s3, S, 20, 20)
    snap, ops = _gets(s3, lambda: cache.get(s3, APP, V, load_log))

    assert ops["GetObject"] == 1  # the new segment only
    assert snap.total == 21
    _assert_full(snap, s3)
    _segment(s3, S, 21, 21)
    _assert_full(cache.get(s3, APP, V, load_log), s3)


def test_a_compaction_listed_before_its_deletes_counts_each_entry_once(s3, monkeypatch):
    for seq in range(6):
        _segment(s3, S, seq, seq)
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    deletes = []
    monkeypatch.setattr(s3, "_delete_keys", deletes.append)
    assert s3.compact_log_segments(APP, V, S)
    _segment(s3, S, 6, 6)
    snap = cache.get(s3, APP, V, load_log)
    assert snap.total == 7
    _assert_full(snap, s3)

    monkeypatch.undo()
    s3._delete_keys(deletes[0])
    _segment(s3, S, 7, 7)
    snap = cache.get(s3, APP, V, load_log)
    assert snap.total == 8
    _assert_full(snap, s3)


def _metric_segment(storage, stream, steps):
    w = MetricWriter(storage, APP, V, stream)
    for step in steps:
        w.add("acc", step / 9, step=step, ts_us=T0 + 10 * step)
    w.flush()


def test_new_metric_segments_are_the_only_metric_reads(s3):
    _segment(s3, S, 0, 0)
    for i in range(10):
        _metric_segment(s3, S, range(3 * i, 3 * i + 3))
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    _metric_segment(s3, S, range(30, 33))
    snap, ops = _gets(s3, lambda: cache.get(s3, APP, V, load_log))

    assert ops["GetObject"] == 1
    assert [p["step"] for p in snap.series()["acc"]] == list(range(33))
    _assert_full(snap, s3)


def test_a_replaced_indexed_object_is_read_again(s3, tmp_path):
    import os
    import tempfile

    from vmn_exp.core.metric_columns import Columns
    from vmn_exp.core.metric_index_file import build_index

    def put(n, replace):
        steps = list(range(n))
        cols = {"acc": Columns(steps, [T0 + s for s in steps], [float(s) for s in steps])}
        fd, path = tempfile.mkstemp(dir=str(tmp_path), suffix=".vmx")
        with os.fdopen(fd, "wb") as f:
            f.write(build_index(S, cols))
        assert s3.put_indexed(APP, V, S, path, replace=replace)

    _segment(s3, S, 0, 0)
    put(3, replace=False)
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    put(50, replace=True)  # a rewind rebuild: same name, more bytes
    snap = cache.get(s3, APP, V, load_log)

    assert len(snap.series()["acc"]) == 50
    _assert_full(snap, s3)


def test_an_object_rewritten_under_its_name_is_read_again(s3):
    _segment(s3, S, 0, 1)
    cache = ParsedLogs()
    cache.get(s3, APP, V, load_log)

    # The record pruned and claimed again: its stream's first object differs
    # from the start, though it only got bigger.
    s3._delete_keys([f"{s3._record_prefix(APP, V)}/log/{S}.jsonl"])
    _segment(s3, S, 0, 2, 3)
    snap = cache.get(s3, APP, V, load_log)

    assert [e["step"] for e in snap.log()] == [2, 3]
    _assert_full(snap, s3)
