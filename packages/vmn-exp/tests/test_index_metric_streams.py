"""The index folds metric streams from block headers (plan 12 §5.3)."""
import random

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store_schema import SCHEMA_VERSION
from vmn_exp.core.log import experiment_row
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
V = "0.0.1-dev.abc.r1"
T0 = 1_700_000_000_000_001  # not a whole second: its ISO form has digits


def _storage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def _row(st):
    rows = ExperimentIndex(st, APP).refresh().rows()
    assert len(rows) == 1
    return rows[0]


def _expected(st):
    meta = st.load_metadata(APP, V)
    return experiment_row(1, meta, st.load_merged_log(APP, V))


def _fields(row):
    """Comparable even with NaNs: their repr."""
    summary = {k: sorted(v.items()) for k, v in row["metric_summary"].items()}
    return repr((sorted(row["metrics"].items()), sorted(summary.items()),
                 row["last_metric_at"]))


def _log_points(st, writer, n, rng, step0=0):
    w = MetricWriter(st, APP, V, writer)
    for i in range(n):
        ts = T0 + (step0 + i) * 1000 + rng.randint(0, 999)
        w.add("loss", rng.random(), step=step0 + i, ts_us=ts)
        if rng.random() < 0.5:
            w.add("acc", rng.choice([rng.random(), float("nan")]), step=step0 + i, ts_us=ts)
        if i % 9 == 0:
            w.flush()
    w.add("sys_cpu", 3.0, ts_us=T0 + 5)
    w.flush()


def test_schema_version_is_bumped():
    assert SCHEMA_VERSION != "exp-index-10"


def test_stream_fold_matches_the_entry_fold(tmp_path):
    st = _storage(tmp_path)
    rng = random.Random(4)
    _log_points(st, "a", 60, rng)
    _log_points(st, "b", 30, rng, step0=10)
    st.append_log_entry(APP, V, "a", {"timestamp": us_to_iso(T0 + 1), "type": "params",
                                       "params": {"lr": 0.1}})
    assert _fields(_row(st)) == _fields(_expected(st))
    assert _row(st)["params"] == {"lr": 0.1}


def test_a_rewind_refolds_the_streams(tmp_path):
    st = _storage(tmp_path)
    w = MetricWriter(st, APP, V, "w")
    for step in range(10):
        w.add("loss", float(step), step=step, ts_us=T0 + step)
    w.flush()
    index = ExperimentIndex(st, APP)
    assert index.refresh().rows()[0]["metrics"]["loss"] == 9.0
    st.append_log_entry(APP, V, "w", {"timestamp": us_to_iso(T0 + 100), "type": "rewind",
                                       "step": 4})
    row = index.refresh().rows()[0]
    assert row["metrics"]["loss"] == 4.0
    assert row["metric_summary"]["loss"]["max"] == 4.0


def test_a_grown_stream_reads_only_its_new_headers(tmp_path, monkeypatch):
    st = _storage(tmp_path)
    w = MetricWriter(st, APP, V, "w")
    for step in range(2000):
        w.add("loss", float(step), step=step, ts_us=T0 + step)
    w.flush()
    index = ExperimentIndex(st, APP)
    index.refresh()
    read = []
    real = st.read_range

    def spy(app, verstr, name, offset, length):
        data = real(app, verstr, name, offset, length)
        read.append(len(data or b""))
        return data

    monkeypatch.setattr(st, "read_range", spy)
    for step in range(2000, 4000):
        w.add("loss", float(step), step=step, ts_us=T0 + step)
    w.flush()
    row = index.refresh().rows()[0]
    assert row["metrics"]["loss"] == 3999.0
    assert row["metric_summary"]["loss"]["min"] == 0.0
    assert 0 < sum(read) < 2000  # a header, not the ~30 KB of points


def test_sealed_parts_and_the_final_index_fold_like_the_stream(tmp_path):
    from vmn_exp.core.metric_compact import compact_writer, seal_writer

    st = _storage(tmp_path)
    rng = random.Random(9)
    _log_points(st, "w", 40, rng)
    index = ExperimentIndex(st, APP)
    index.refresh()
    assert seal_writer(st, APP, V, "w") == 1
    _log_points(st, "w", 40, rng, step0=40)
    assert _fields(index.refresh().rows()[0]) == _fields(_expected(st))
    assert _fields(_row(st)) == _fields(_expected(st))
    expected = _fields(_expected(st))
    assert compact_writer(st, APP, V, "w")
    assert _fields(index.refresh().rows()[0]) == expected


def test_a_vmx_rewritten_larger_refolds_like_a_cold_build(tmp_path):
    from vmn_exp.core.metric_compact import compact_writer, reopen_writer

    st = _storage(tmp_path)
    rng = random.Random(11)
    _log_points(st, "w", 40, rng)
    assert compact_writer(st, APP, V, "w")
    index = ExperimentIndex(st, APP)
    index.refresh()
    assert reopen_writer(st, APP, V, "w") == 1
    _log_points(st, "w", 40, rng, step0=40)
    assert compact_writer(st, APP, V, "w")
    assert _fields(index.refresh().rows()[0]) == _fields(_row(st))
