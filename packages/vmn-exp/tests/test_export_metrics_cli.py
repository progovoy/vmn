"""``vmn-exp export-metrics``: a long table ``(run, writer, key, step, ts,
value)`` of runs' metric series, as Parquet (pyarrow) or CSV (plan 12 §8.3)."""
import csv
import sys

import pytest
from exp_helpers import _bootstrap, _exp, _experiment, _storage, extract_dev_verstr

from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.series_reader import SeriesReader

T0 = 1_767_225_600_000_000
COLUMNS = ["run", "writer", "key", "step", "ts", "value"]


def _run(app_layout, capfd, writers=("w",)):
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="create") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    storage = _storage(app_layout)
    for name in writers:
        w = MetricWriter(storage, app_layout.app_name, verstr, name)
        for step in (1, 2):
            w.add("loss", 1.0 / step, step=step, ts_us=T0 + step)
            w.add("acc", 0.5 * step, step=step, ts_us=T0 + step)
        w.flush()
    return verstr


def _export(app_layout, *args):
    return _exp(app_layout.app_name, action="export-metrics", extra_args=list(args))


def _csv_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_series_reader_rows_carry_the_writer(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _run(app_layout, capfd, writers=("a", "b"))
    reader = SeriesReader.from_storage(_storage(app_layout), app_layout.app_name, verstr)
    rows = list(reader.rows(keys=["loss"]))
    assert sorted((w, k, s) for w, k, s, _, _ in rows) == [
        ("a", "loss", 1), ("a", "loss", 2), ("b", "loss", 1), ("b", "loss", 2)]
    assert {v for *_, v in rows} == {1.0, 0.5}


def test_export_metrics_csv_writes_long_rows_of_every_run(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    a, b = _run(app_layout, capfd), _run(app_layout, capfd)
    out = tmp_path / "m.csv"
    assert _export(app_layout, "-v", a, "-v", b, "-o", str(out)) == 0
    rows = _csv_rows(out)
    assert list(rows[0]) == COLUMNS
    assert len(rows) == 8
    assert {r["run"] for r in rows} == {a, b}
    first = next(r for r in rows if r["run"] == a and r["key"] == "loss" and r["step"] == "1")
    assert first["writer"] == "w" and float(first["value"]) == 1.0
    assert int(first["ts"]) == T0 + 1


def test_export_metrics_keys_filter(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    a = _run(app_layout, capfd)
    out = tmp_path / "m.csv"
    assert _export(app_layout, "-v", a, "--keys", "acc", "--format", "csv",
                   "-o", str(out)) == 0
    assert {r["key"] for r in _csv_rows(out)} == {"acc"}


def test_export_metrics_needs_a_run_ref(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    _run(app_layout, capfd)
    assert _export(app_layout, "-o", str(tmp_path / "m.csv")) == 1


def test_export_metrics_parquet(app_layout, capfd, tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    _bootstrap(app_layout)
    a = _run(app_layout, capfd)
    out = tmp_path / "m.parquet"
    assert _export(app_layout, "-v", a, "-o", str(out)) == 0
    table = pq.read_table(out)
    assert table.column_names == COLUMNS
    assert table.num_rows == 4


def test_export_metrics_parquet_without_pyarrow_errors(app_layout, capfd, tmp_path,
                                                        monkeypatch):
    from vmn_exp.cli import export_metrics

    monkeypatch.setitem(sys.modules, "pyarrow", None)
    _bootstrap(app_layout)
    a = _run(app_layout, capfd)
    capfd.readouterr()
    out = tmp_path / "m.parquet"
    assert export_metrics.experiment_export_metrics(
        _storage(app_layout), app_layout.app_name,
        _Args(version=[a], output=str(out))) == 1
    captured = capfd.readouterr()
    assert "vmn-exp[parquet]" in captured.out + captured.err
    assert not out.exists()


class _Args:
    def __init__(self, version, output, keys=None, metrics_format=None):
        self.version, self.output = version, output
        self.keys, self.metrics_format = keys, metrics_format
