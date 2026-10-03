"""The run-detail log cache reads metric streams too (plan 12 §5.5): a grown
stream costs its new blocks, and the result equals a full parse."""
import pytest

from vmn_exp.core.log import load_log, metric_series
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.snapshot import open_storage
from vmn_exp.ui.readers import parsed_logs
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP = "app"
V = "1.0.0-dev.a"
T0 = 1_767_225_600_000_001


@pytest.fixture
def storage(tmp_path):
    (tmp_path / ".git").mkdir()
    s = open_storage(root=str(tmp_path), area="runs")
    s.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    s.append_log_entry(APP, V, "w", {"timestamp": "2026-01-01T00:00:00.000001Z",
                                     "type": "create", "params": {"lr": 0.1}})
    return s


def _log(storage, writer, start, stop):
    w = MetricWriter(storage, APP, V, writer)
    for step in range(start, stop):
        w.add("loss", step / 7, step=step, ts_us=T0 + 10 * step)
    w.flush()


def _assert_full(snap, storage):
    full = load_log(storage, APP, V)
    assert snap.log() == full
    assert snap.series() == metric_series(full)
    assert snap.metrics == {"lr": 0.1, "loss": snap.metrics["loss"]}


def test_stream_points_show_in_the_series(storage):
    _log(storage, "w", 0, 5)
    snap = ParsedLogs().get(storage, APP, V, load_log)
    assert [p["step"] for p in snap.series()["loss"]] == [0, 1, 2, 3, 4]
    _assert_full(snap, storage)


def test_a_grown_stream_is_read_from_its_offset(storage, monkeypatch):
    cache = ParsedLogs()
    _log(storage, "w", 0, 5)
    cache.get(storage, APP, V, load_log)
    monkeypatch.setattr(parsed_logs, "_parse_with", None)  # no full re-parse
    _log(storage, "w", 5, 9)
    _log(storage, "x", 9, 10)
    snap = cache.get(storage, APP, V, load_log)
    assert [p["step"] for p in snap.series()["loss"]] == list(range(10))
    monkeypatch.undo()
    _assert_full(snap, storage)


def test_a_sealed_part_reparses_even_when_the_new_stream_outgrew_the_old(storage):
    from vmn_exp.core.metric_compact import seal_writer

    cache = ParsedLogs()
    _log(storage, "w", 0, 3)
    cache.get(storage, APP, V, load_log)
    seal_writer(storage, APP, V, "w")
    _log(storage, "w", 3, 20)
    snap = cache.get(storage, APP, V, load_log)
    assert [p["step"] for p in snap.series()["loss"]] == list(range(20))
    _assert_full(snap, storage)
