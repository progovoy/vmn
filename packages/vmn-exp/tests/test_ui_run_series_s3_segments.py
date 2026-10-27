"""``run_series`` (a run page's joined series, Compare, outer-run charts) on an
S3 store, re-asked on every poll of a live run: its log and metric segments
are written once each, so a poll GETs only the segments shipped since the
last one — and answers what a fresh read does."""
import json

import pytest
from s3_helpers import meta, mocked_bucket, op_counts, record_calls, s3_storage
from vmn_exp.core.log import load_log
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.ui.readers import experiment_detail, segment_cache
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP, V = "app", "1.0.0-dev.a"
S = "w~o1"
T0 = 1_767_225_600_000_000
CASES = [dict(keys=None, x=None), dict(keys=["loss"], x={"loss": "epoch"})]


@pytest.fixture
def s3(monkeypatch):
    # Each test's bucket reuses names: none may see another's kept segments.
    monkeypatch.setattr(segment_cache, "_SEGMENTS", segment_cache.SegmentCache())
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save(APP, V, meta(V), {})
        yield storage


def _log_segment(storage, seq, entry):
    line = json.dumps(dict(entry, timestamp=f"2026-01-01T00:00:00.{seq:06d}Z")) + "\n"
    assert storage.create_log_segment(APP, V, S, seq, line.encode())


def _metric_segment(storage, steps):
    w = MetricWriter(storage, APP, V, S)
    for step in steps:
        w.add("loss", 1 / (step + 1), step=step, ts_us=T0 + 10 * step)
        w.add("epoch", float(step // 4), step=step, ts_us=T0 + 10 * step)
    w.flush()


def _live_run(storage):
    _log_segment(storage, 0, {"type": "create", "params": {"lr": 0.1}})
    _log_segment(storage, 1, {"type": "define_metric", "name": "loss", "goal": "min"})
    for i in range(20):
        _metric_segment(storage, range(3 * i, 3 * i + 3))


def _parsed_path(storage, keys, x):
    snapshot = ParsedLogs().get(storage, APP, V, load_log)
    series, totals = experiment_detail.thinned_series(snapshot, keys, 2000, None, x)
    return series, totals, snapshot.step_metrics(None)


def _series(storage, case):
    return experiment_detail.run_series(storage, APP, V, case["keys"], 2000, x=case["x"])


@pytest.mark.parametrize("case", CASES)
def test_a_repeated_read_gets_only_the_new_segments(s3, case):
    _live_run(s3)
    _series(s3, case)

    _metric_segment(s3, range(60, 63))
    _metric_segment(s3, range(63, 66))
    _log_segment(s3, 2, {"type": "note", "note": "half way"})
    calls = record_calls(s3._s3)
    got = _series(s3, case)

    assert op_counts(calls)["GetObject"] <= 1 + 3  # metadata.yml + the new segments
    assert got == _parsed_path(s3, **case)
    assert len(got[0]["loss"]) == 66


def test_a_segment_written_again_with_other_bytes_of_its_size_is_read_again(s3):
    _live_run(s3)
    _log_segment(s3, 2, {"type": "metrics", "step": 99, "values": {"v1": 0.5}})
    _series(s3, CASES[0])
    s3._delete_keys([f"{s3._record_prefix(APP, V)}/log/{S}@000002.jsonl"])
    _log_segment(s3, 2, {"type": "metrics", "step": 99, "values": {"v1": 0.7}})

    got = _series(s3, CASES[0])
    assert [p["value"] for p in got[0]["v1"]] == [0.7]
    assert got == _parsed_path(s3, **CASES[0])


def test_a_compacted_run_reads_its_index_not_stale_segments(s3, tmp_path):
    from vmn_exp.core.metric_compact import compact_record

    _live_run(s3)
    _series(s3, CASES[0])
    compact_record(s3, APP, V)
    _metric_segment(s3, range(60, 61))

    assert _series(s3, CASES[0]) == _parsed_path(s3, **CASES[0])
