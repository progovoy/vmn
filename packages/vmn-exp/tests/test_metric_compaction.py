"""Compaction (plan 12 §6): a stream's ``.vms`` becomes its ``.vmx``; a long
writer seals its stream every SEAL_POINTS points and goes on in a new one."""
import random

from test_series_reader import APP, V, _entries, _same, _storage, _write

from vmn_exp.core import metric_compact
from vmn_exp.core.log import metric_series
from vmn_exp.core.metric_compact import compact_record, compact_writer, seal_writer
from vmn_exp.core.metric_files import indexed_name, is_indexed_file, is_stream_file
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.core.writer import own_stream


def _series(storage, rewinds=()):
    return metric_series(SeriesReader.from_storage(storage, APP, V, rewinds=rewinds))


def _names(storage, writer="w"):
    return [n for n, _ in storage.metric_objects(APP, V)[writer]]


def _footer(storage, writer="w"):
    [(name, size)] = storage.metric_objects(APP, V)[writer]
    read = lambda off, n: storage.read_range(APP, V, name, off, n)  # noqa: E731
    return MetricIndexReader(read, size).footer


def test_compaction_replaces_the_stream_and_keeps_every_series(tmp_path):
    storage = _storage(tmp_path)
    _write(storage, "w", _entries(random.Random(5), 300, 1_700_000_000_000_000))
    before = _series(storage)
    assert compact_writer(storage, APP, V, "w")
    assert _names(storage) == [indexed_name("w")]
    _same(_series(storage), before)


def test_a_compacted_writer_is_not_compacted_again(tmp_path):
    storage = _storage(tmp_path)
    _write(storage, "w", _entries(random.Random(6), 20, 1_700_000_000_000_000))
    assert compact_writer(storage, APP, V, "w")
    assert compact_writer(storage, APP, V, "w") is False


def test_compaction_applies_the_rewinds(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    for step in range(5):
        w.add("loss", float(step), step=step, ts_us=1_000 + step)
    w.flush()
    assert compact_writer(storage, APP, V, "w", rewinds=[(2, 1_500)])
    assert [p["step"] for p in _series(storage)["loss"]] == [0, 1, 2]
    assert _footer(storage)["rewinds_applied"] is True


def test_rebuild_drops_what_a_newer_rewind_hides(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    for step in range(5):
        w.add("loss", float(step), step=step, ts_us=1_000 + step)
    w.flush()
    compact_writer(storage, APP, V, "w")
    assert compact_writer(storage, APP, V, "w", rewinds=[(1, 9_000)], rebuild=True)
    assert [p["step"] for p in _series(storage)["loss"]] == [0, 1]


def test_compact_record_compacts_every_streaming_writer(tmp_path):
    storage = _storage(tmp_path)
    for writer in ("a", "b"):
        _write(storage, writer, _entries(random.Random(7), 30, 1_700_000_000_000_000))
    assert compact_record(storage, APP, V) == ["a", "b"]
    assert compact_record(storage, APP, V) == []


def _all_names(storage):
    return sorted(n for names in storage.metric_objects(APP, V).values() for n, _ in names)


def test_sealed_streams_and_later_blocks_read_as_one_series_and_compact_at_finish(tmp_path):
    storage = _storage(tmp_path)
    entries = _entries(random.Random(8), 400, 1_700_000_000_000_000)
    _write(storage, own_stream(storage, APP, V), entries[:200])
    assert seal_writer(storage, APP, V, own_stream(storage, APP, V))
    _write(storage, own_stream(storage, APP, V), entries[200:300])
    assert seal_writer(storage, APP, V, own_stream(storage, APP, V))
    _write(storage, own_stream(storage, APP, V), entries[300:])
    names = _all_names(storage)
    assert sum(map(is_indexed_file, names)) == 2 and sum(map(is_stream_file, names)) == 1
    reference = _storage(tmp_path / "ref")
    _write(reference, "w", entries)
    _same(_series(storage), _series(reference))
    assert compact_writer(storage, APP, V, own_stream(storage, APP, V))
    assert all(map(is_indexed_file, _all_names(storage)))
    _same(_series(storage), _series(reference))


def test_writers_seal_their_stream_once_they_pass_the_seal_threshold(tmp_path, monkeypatch):
    from vmn_exp.core.writer import append_metric_entries

    monkeypatch.setattr(metric_compact, "SEAL_POINTS", 10)
    monkeypatch.setenv("VMN_WRITER_ID", "w")
    monkeypatch.setattr("vmn_exp.core.writer._WRITER_ID", None)
    storage = _storage(tmp_path)
    for i in range(5):
        entry = {"type": "metrics", "step": i, "timestamp": "2026-01-01T00:00:0%dZ" % i,
                 "values": {"a": 1.0, "b": 2.0, "c": 3.0}}
        assert append_metric_entries(storage, APP, V, [entry])
    names = _all_names(storage)
    assert any(map(is_indexed_file, names)) and any(map(is_stream_file, names))
    assert len(_series(storage)["a"]) == 5


def test_a_resumed_writer_keeps_its_compacted_points_and_streams_on(tmp_path):
    storage = _storage(tmp_path)
    entries = _entries(random.Random(10), 200, 1_700_000_000_000_000)
    _write(storage, own_stream(storage, APP, V), entries[:100])
    assert compact_writer(storage, APP, V, own_stream(storage, APP, V))
    _write(storage, own_stream(storage, APP, V), entries[100:])
    reference = _storage(tmp_path / "ref")
    _write(reference, "w", entries)
    _same(_series(storage), _series(reference))
    assert compact_writer(storage, APP, V, own_stream(storage, APP, V))
    assert all(map(is_indexed_file, _all_names(storage)))
    _same(_series(storage), _series(reference))
