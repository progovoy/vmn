"""SeriesReader (plan 12 §5.1-§5.2): series over ``.vmx`` + ``.vms`` streams.

The golden tests keep a copy of the v1 algorithm (``metric_series`` over the
merged JSONL log) and check the reader gives the same series for the same
logical data written as metric streams.
"""
import os
import random
import tempfile

from s3_helpers import meta

from vmn_exp.core.log import metric_series
from vmn_exp.core.metric_entries import record_metric_entries
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.storage.files import flatten_logs
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V = "app", "v1"


def _old_metric_series(log):
    """plan 12 v1: per-metric points from ``type == metrics`` entries."""
    series = {}
    for entry in log:
        if entry.get("type") != "metrics":
            continue
        for key, value in (entry.get("values") or {}).items():
            series.setdefault(key, []).append(
                {"step": entry.get("step"), "ts": entry.get("timestamp"), "value": value})
    return series


def _storage(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), "runs")
    storage.save(APP, V, meta(V), {})
    return storage


def _entries(rng, n, start_us, keys=("loss", "acc", "lr")):
    out, ts = [], start_us
    for i in range(n):
        ts += rng.randint(1, 5_000)
        values = {k: rng.choice([rng.random(), float("nan"), float("inf")])
                  if rng.random() < 0.05 else rng.random()
                  for k in keys if rng.random() < 0.7}
        if not values:
            continue
        entry = {"timestamp": us_to_iso(ts), "type": "metrics", "values": values}
        if rng.random() < 0.9:
            entry["step"] = i
        out.append(entry)
    return out


def _write(storage, writer, entries, flush_every=7):
    w = MetricWriter(storage, APP, V, writer)
    for i in range(0, len(entries), flush_every):
        assert record_metric_entries(w, entries[i:i + flush_every])
    return w


def _same(a, b):
    assert set(a) == set(b)
    for key in a:
        assert [(p["step"], p["ts"]) for p in a[key]] == [(p["step"], p["ts"]) for p in b[key]]
        assert [repr(p["value"]) for p in a[key]] == [repr(p["value"]) for p in b[key]]


def test_golden_one_writer_matches_v1(tmp_path):
    rng = random.Random(1)
    entries = _entries(rng, 400, 1_700_000_000_000_000)
    storage = _storage(tmp_path)
    _write(storage, "w", entries)
    got = metric_series(SeriesReader.from_storage(storage, APP, V))
    _same(got, _old_metric_series(flatten_logs({"w": entries})))


def test_golden_several_writers_merge_like_the_merged_log(tmp_path):
    rng = random.Random(2)
    logs = {w: _entries(rng, 150, 1_700_000_000_000_000) for w in ("b", "a", "c")}
    storage = _storage(tmp_path)
    for writer, entries in logs.items():
        _write(storage, writer, entries, flush_every=rng.randint(1, 20))
    got = metric_series(SeriesReader.from_storage(storage, APP, V))
    _same(got, _old_metric_series(flatten_logs(logs)))


def test_golden_indexed_writer_matches_its_stream(tmp_path):
    rng = random.Random(3)
    entries = [e for e in _entries(rng, 300, 1_700_000_000_000_000) if "step" in e]
    storage = _storage(tmp_path)
    _write(storage, "w", entries)
    streamed = metric_series(SeriesReader.from_storage(storage, APP, V))
    reader = SeriesReader.from_storage(storage, APP, V)
    keys = {k: reader.points(k) for k in reader.keys()}
    fd, path = tempfile.mkstemp(dir=tmp_path)
    os.write(fd, build_index("w", keys))
    os.close(fd)
    assert storage.put_indexed(APP, V, "w", path)
    _same(metric_series(SeriesReader.from_storage(storage, APP, V)), streamed)


def test_rewind_hides_earlier_points_past_its_step(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    for step in range(5):
        w.add("loss", float(step), step=step, ts_us=1_000 + step)
    w.flush()
    w.add("loss", 9.0, step=3, ts_us=2_000)
    w.flush()
    reader = SeriesReader.from_storage(storage, APP, V, rewinds=[(2, 1_500)])
    assert [(p["step"], p["value"]) for p in metric_series(reader)["loss"]] == [
        (0, 0.0), (1, 1.0), (2, 2.0), (3, 9.0)]


def test_rewinds_come_from_the_log_entries(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    w.add("loss", 1.0, step=5, ts_us=1_000)
    w.flush()
    log = [{"type": "rewind", "step": 2, "timestamp": us_to_iso(2_000)}]
    reader = SeriesReader.from_storage(storage, APP, V, log=log)
    assert reader.keys() == {}


def test_step_less_twin_merges_back_into_its_key(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    w.add("x", 1.0, step=0, ts_us=10)
    w.flush()
    w.add("x", 2.0, ts_us=20)
    w.flush()
    series = metric_series(SeriesReader.from_storage(storage, APP, V))
    assert [(p["step"], p["value"]) for p in series["x"]] == [(0, 1.0), (None, 2.0)]


def test_points_filter_by_step_range(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    for step in range(10):
        w.add("x", float(step), step=step, ts_us=step + 1)
    w.flush()
    cols = SeriesReader.from_storage(storage, APP, V).points("x", step_range=(3, 5))
    assert list(cols.steps) == [3, 4, 5] and list(cols.values) == [3.0, 4.0, 5.0]


def test_thinned_keeps_first_last_and_extremes(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    for step in range(1000):
        w.add("x", 100.0 if step == 500 else 0.0, step=step, ts_us=step + 1)
    w.flush()
    thinned = SeriesReader.from_storage(storage, APP, V).thinned("x", 50)
    assert len(thinned) <= 50
    assert thinned[0]["step"] == 0 and thinned[-1]["step"] == 999
    assert max(p["value"] for p in thinned) == 100.0


def test_keys_count_points_without_reading_values(tmp_path):
    storage = _storage(tmp_path)
    w = MetricWriter(storage, APP, V, "w")
    w.add("x", 1.0, step=0, ts_us=1)
    w.add("y", 1.0, step=0, ts_us=1)
    w.flush()
    w.add("x", 2.0, step=1, ts_us=2)
    w.flush()
    assert SeriesReader.from_storage(storage, APP, V).keys() == {"x": 2, "y": 1}


def test_legacy_entries_are_one_more_source():
    log = [{"timestamp": us_to_iso(5), "type": "metrics", "values": {"x": 1.0}, "step": 0}]
    assert metric_series(log) == {"x": [{"step": 0, "ts": us_to_iso(5), "value": 1.0}]}


def test_entries_by_writer_regroup_points_of_one_call(tmp_path):
    storage = _storage(tmp_path)
    entries = [{"timestamp": us_to_iso(7), "type": "metrics",
                "values": {"a": 1.0, "b": 2.0}, "step": 3}]
    _write(storage, "w", entries)
    assert SeriesReader.from_storage(storage, APP, V).entries_by_writer() == {"w": entries}
