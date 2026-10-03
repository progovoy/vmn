"""A key logged step-less in one block and with a step in another (separate
MetricWriters, as ``append_metric_entries`` builds one per call) compacts
with both kinds of points, whichever came first."""
import pytest

from test_series_reader import APP, V, _storage

from vmn_exp.core.metric_compact import compact_writer, seal_writer
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.series_reader import SeriesReader


def _block(storage, step, value, ts_us):
    w = MetricWriter(storage, APP, V, "w")
    w.add("loss", value, step=step, ts_us=ts_us)
    assert w.flush()


def _points(storage, step_range=None):
    cols = SeriesReader.from_storage(storage, APP, V).points("loss", step_range)
    return list(zip(cols.steps, cols.ts, cols.values))


ORDERS = {
    "stepless_first": [(None, 0.9, 1_000), (1, 0.8, 2_000), (2, 0.7, 3_000)],
    "stepped_first": [(1, 0.8, 1_000), (None, 0.9, 2_000), (2, 0.7, 3_000)],
}


def _expected(order):
    return [(s, t, v) for s, v, t in ORDERS[order]]


@pytest.mark.parametrize("order", sorted(ORDERS))
def test_mixed_blocks_compact_with_both_kinds_of_points(tmp_path, order):
    storage = _storage(tmp_path)
    for step, value, ts in ORDERS[order]:
        _block(storage, step, value, ts)
    assert _points(storage) == _expected(order)
    assert compact_writer(storage, APP, V, "w")
    assert _points(storage) == _expected(order)
    assert _points(storage, (1, 2)) == [p for p in _expected(order) if p[0] is not None]
    assert [p[0] for p in _points(storage, (2, None))] == [2]


@pytest.mark.parametrize("order", sorted(ORDERS))
def test_mixed_blocks_seal_and_merge(tmp_path, order):
    storage = _storage(tmp_path)
    for step, value, ts in ORDERS[order]:
        _block(storage, step, value, ts)
    assert seal_writer(storage, APP, V, "w") == 1
    assert _points(storage) == _expected(order)
    assert compact_writer(storage, APP, V, "w")
    assert _points(storage) == _expected(order)
