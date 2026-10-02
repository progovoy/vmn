"""MetricWriter (plan 12 §4.1): per-key buffers, one block per flush."""
import pytest

from vmn_exp.core.metric_block import decode_blocks
from vmn_exp.core.metric_stream import MetricWriter, stepless_twin


class FakeStorage:
    def __init__(self, ok=True):
        self.blocks, self.ok = [], ok

    def append_metric_block(self, app, verstr, writer, data):
        if not self.ok:
            raise OSError("down")
        self.blocks.append((app, verstr, writer, data))
        return True


def _writer(storage):
    return MetricWriter(storage, "app", "v1", "w", clock=lambda: 10.0)


def _keys(storage, i=-1):
    return next(decode_blocks(storage.blocks[i][3])).keys


def test_flush_writes_one_block_with_every_buffered_key():
    s = FakeStorage()
    w = _writer(s)
    w.add("loss", 0.5, step=1, ts=1.0)
    w.add("acc", 0.9, step=1, ts=1.0)
    w.add("loss", 0.4, step=2, ts=2.0)
    assert w.flush()
    assert len(s.blocks) == 1 and s.blocks[0][:3] == ("app", "v1", "w")
    keys = _keys(s)
    assert list(keys["loss"].steps) == [1, 2]
    assert list(keys["loss"].values) == [0.5, 0.4]
    assert list(keys["loss"].ts) == [1_000_000, 2_000_000]
    assert list(keys["acc"].values) == [0.9]


def test_flush_with_nothing_buffered_writes_nothing():
    s = FakeStorage()
    w = _writer(s)
    assert w.flush()
    w.add("x", 1.0, step=0)
    w.flush()
    w.flush()
    assert len(s.blocks) == 1


def test_each_flush_starts_a_new_block():
    s = FakeStorage()
    w = _writer(s)
    w.add("x", 1.0, step=0)
    w.flush()
    w.add("x", 2.0, step=1)
    w.flush()
    assert [list(_keys(s, i)["x"].values) for i in (0, 1)] == [[1.0], [2.0]]


def test_missing_timestamp_comes_from_the_clock():
    s = FakeStorage()
    w = _writer(s)
    w.add("x", 1.0, step=0)
    w.flush()
    assert list(_keys(s)["x"].ts) == [10_000_000]


def test_a_stepless_key_has_no_steps():
    s = FakeStorage()
    w = _writer(s)
    w.add("sys_cpu", 3.0)
    w.flush()
    assert not _keys(s)["sys_cpu"].has_step


def test_a_key_logged_with_and_without_step_splits_into_a_stepless_twin():
    s = FakeStorage()
    w = _writer(s)
    w.add("loss", 1.0, step=0)
    w.add("loss", 2.0)
    w.flush()
    keys = _keys(s)
    assert keys["loss"].has_step and list(keys["loss"].values) == [1.0]
    twin = keys[stepless_twin("loss")]
    assert not twin.has_step and list(twin.values) == [2.0]


def test_the_split_holds_across_flushes():
    s = FakeStorage()
    w = _writer(s)
    w.add("loss", 1.0, step=0)
    w.flush()
    w.add("loss", 2.0)
    w.flush()
    assert set(_keys(s)) == {stepless_twin("loss")}


def test_a_stepless_key_logged_with_a_step_later_moves_its_stepless_points_to_the_twin():
    s = FakeStorage()
    w = _writer(s)
    w.add("loss", 1.0)
    w.add("loss", 2.0, step=3)
    w.flush()
    keys = _keys(s)
    assert list(keys["loss"].steps) == [3]
    assert list(keys[stepless_twin("loss")].values) == [1.0]


def test_a_failed_append_keeps_the_points_for_the_next_flush():
    s = FakeStorage(ok=False)
    w = _writer(s)
    w.add("x", 1.0, step=0)
    with pytest.raises(OSError):
        w.flush()
    s.ok = True
    w.add("x", 2.0, step=1)
    w.flush()
    assert list(_keys(s)["x"].values) == [1.0, 2.0]


def test_a_refused_append_reports_false_and_keeps_the_points():
    class Refusing(FakeStorage):
        def append_metric_block(self, *a):
            return False

    s = Refusing()
    w = _writer(s)
    w.add("loss", 0.5, step=1)
    assert w.flush() is False
    s.append_metric_block = FakeStorage.append_metric_block.__get__(s)
    assert w.flush()
    assert list(_keys(s)["loss"].values) == [0.5]
