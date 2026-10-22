"""Opening a ``.vmx`` costs one ranged GET when its footer fits the first
read from the end (the index folds every finished run from its footer), and
still two when the footer is bigger."""
import pytest

from vmn_exp.core import metric_index_reader
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import MetricIndexReader, build_index


def _data():
    return build_index("w", {"loss": Columns([1, 2, 3], [10, 20, 30], [3.0, 2.0, 1.0]),
                             "acc": Columns(None, [10, 20], [0.5, 0.6])})


def _open(data, log):
    def read_range(offset, length):
        log.append((offset, length))
        return data[offset:offset + length]

    return MetricIndexReader(read_range, len(data))


def test_a_small_footer_costs_one_read():
    log = []
    reader = _open(_data(), log)
    assert len(log) == 1
    assert sorted(reader.keys()) == ["acc", "loss"]


def test_a_footer_past_the_first_read_still_opens(monkeypatch):
    monkeypatch.setattr(metric_index_reader, "FOOTER_READ_BYTES", 16)
    log = []
    reader = _open(_data(), log)
    assert len(log) == 2
    assert [p["value"] for p in reader.points("loss")] == [3.0, 2.0, 1.0]


def test_a_corrupt_footer_still_raises():
    data = bytearray(_data())
    data[-20] ^= 0xFF
    with pytest.raises(ValueError):
        _open(bytes(data), [])
