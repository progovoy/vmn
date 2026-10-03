"""Log views never merge two points of one key logged at the same timestamp:
the stream and the compacted ``.vmx`` read as the same entries, so a row over
the merged log keeps the key's summary either way."""
import pytest

from s3_helpers import meta
from test_series_reader import APP, V, _storage

from vmn_exp.core.log import experiment_row
from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.metric_entries import points_to_entries
from vmn_exp.core.metric_stream import MetricWriter

CASES = {
    "same_step": [("sys_cpu", 10.0, None), ("sys_cpu", 30.0, None)],
    "different_steps": [("loss", 0.9, 1), ("loss", 0.7, 2)],
    "interleaved_same_step": [("loss", 0.9, 1), ("acc", 0.1, 1), ("loss", 0.7, 1)],
}


def _write(storage, points, one_block):
    w = MetricWriter(storage, APP, V, "w")
    for key, value, step in points:
        w.add(key, value, step=step, ts_us=1_000)
        if not one_block:
            assert w.flush()
    if one_block:
        assert w.flush()


def _metric_entries(storage):
    log = storage.load_merged_log(APP, V)
    return log, sorted((sorted(e["values"].items()), e.get("step") or 0)
                       for e in log if e.get("type") == "metrics")


def _flat(entries):
    return sorted((key, value, step) for values, step in entries for key, value in values)


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("one_block", [False, True])
def test_log_view_and_row_equal_before_and_after_compaction(tmp_path, case, one_block):
    storage = _storage(tmp_path)
    _write(storage, CASES[case], one_block)
    log_before, before = _metric_entries(storage)
    row_before = experiment_row(1, meta(V), log_before)
    assert compact_writer(storage, APP, V, "w")
    log_after, after = _metric_entries(storage)
    row_after = experiment_row(1, meta(V), log_after)
    if len({key for key, _, _ in CASES[case]}) == 1:
        assert after == before
    # a .vmx keeps no cross-key order within one timestamp: compare points
    assert _flat(after) == _flat(before)
    assert len(_flat(after)) == len(CASES[case])
    assert row_after["metrics"] == row_before["metrics"]
    assert row_after.get("metric_summary") == row_before.get("metric_summary")
    assert CASES[case][0][0] in row_after["metric_summary"]


def test_points_to_entries_starts_a_new_entry_when_a_key_repeats():
    points = [(5, 1, "loss", 0.9), (5, 1, "acc", 0.1), (5, 1, "loss", 0.7), (5, 1, "acc", 0.2)]
    entries = points_to_entries(points)
    assert [e["values"] for e in entries] == [{"loss": 0.9, "acc": 0.1},
                                             {"loss": 0.7, "acc": 0.2}]
