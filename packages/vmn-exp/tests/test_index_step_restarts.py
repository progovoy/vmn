"""Index rows carry ``step_restarts`` for a metric whose steps went back,
from its streams and ``.vmx`` files — old ones (no restart points written)
included: they are read point by point, or from their columns."""
import json
import zlib

from test_vmx_write_order import APP, V, _compacted_run

from vmn_exp.core import metric_block, metric_stream
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_columns import key_summary
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.snapshot import LocalSnapshotStorage

T0 = 1_700_000_000_000_001
RESTARTED = {"best": {"from": 120, "to": 5}}


def _old_block(keys, inherited=False):
    """A block as an older vmn-exp encoded it: no ``order``, no ``r``."""
    header = {"keys": [key_summary(name, cols) for name, cols in keys.items()],
              "inherited": bool(inherited)}
    body = zlib.compress(b"".join(metric_block._pack_key(cols) for cols in keys.values()))
    head = json.dumps(header, separators=(",", ":")).encode()
    prefix = metric_block._PREFIX.pack(metric_block.MAGIC, metric_block.VERSION, len(head),
                                       len(body), zlib.crc32(head + body))
    return prefix + head + body


def _row(st):
    [row] = ExperimentIndex(st, APP).refresh().rows()
    return row


def _stream(tmp_path, steps):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    w = MetricWriter(st, APP, V, "w")
    for i, step in enumerate(steps):
        w.add("best", 0.5, step=step, ts_us=T0 + i)
    w.flush()
    return st


def test_a_compacted_run_marks_its_restart(tmp_path):
    assert _row(_compacted_run(tmp_path))["step_restarts"] == RESTARTED


def test_an_old_footer_marks_its_restart_from_its_columns(tmp_path):
    assert _row(_compacted_run(tmp_path, old=True))["step_restarts"] == RESTARTED


def test_a_stream_marks_a_restart_inside_a_block(tmp_path):
    assert _row(_stream(tmp_path, [0, 1, 2, 0, 1]))["step_restarts"] == {
        "best": {"from": 2, "to": 1}}


def test_an_old_block_is_read_point_by_point(tmp_path, monkeypatch):
    monkeypatch.setattr(metric_stream, "encode_block", _old_block)
    assert _row(_stream(tmp_path, [0, 1, 2, 0, 1]))["step_restarts"] == {
        "best": {"from": 2, "to": 1}}


def test_monotone_streams_carry_no_mark(tmp_path):
    assert "step_restarts" not in _row(_stream(tmp_path, [0, 1, 2, 3]))


def test_a_new_vmx_folds_from_its_footer_alone(tmp_path, monkeypatch):
    st = _compacted_run(tmp_path)

    def unread(*args, **kwargs):
        raise AssertionError("a marked footer's columns were read")

    monkeypatch.setattr(MetricIndexReader, "points", unread)
    monkeypatch.setattr(MetricIndexReader, "column", unread)
    assert _row(st)["step_restarts"] == RESTARTED
