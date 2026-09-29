"""pandas views of the read side: runs_dataframe() and get_metric_history().

The flattening is pure Python and tested without pandas; the DataFrame tests
skip when pandas (the optional ``vmn-exp-sdk[pandas]`` extra) is absent.
"""
import builtins
import datetime
import json
import os

import pytest
import yaml
from helpers import _storage

from vmn_exp.core.inputs import create_input_entry
from vmn_exp.core.writer import create_tags_entry
from vmn_exp.sdk import frames
from vmn_exp.sdk.reader import get_metric_history, runs_dataframe

_T0 = "2026-09-21T12:00:01Z"
_T1 = "2026-09-21T12:00:02.500000Z"


def _write_run(app_layout, verstr, log, parent=None, name=None, run_state=None):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    meta = {"verstr": verstr, "code_verstr": verstr, "timestamp": _T0,
            "branch": "master", "base_version": "0.0.1"}
    if parent:
        meta["parent"] = parent
    if name:
        meta["name"] = name
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    if run_state:
        with open(os.path.join(path, "run_state.yml"), "w") as f:
            yaml.dump(run_state, f)
    with open(os.path.join(path, "log.w0.jsonl"), "w") as f:
        for entry in log:
            f.write(json.dumps(entry) + "\n")


def _metrics(ts, values, step=None):
    return {"timestamp": ts, "type": "metrics", "values": values, "step": step}


def _seed(app_layout):
    finished = {"state": "finished", "exit_code": 0, "started_at": _T0,
                "finished_at": _T1, "duration_sec": 1.5, "host": "box"}
    _write_run(app_layout, "0.0.1", [
        {"timestamp": _T0, "type": "params", "params": {"model": "xgb", "lr": 0.1}},
        _metrics(_T0, {"loss": 0.9}, step=0),
        _metrics(_T1, {"loss": 0.4}, step=1),
        create_tags_entry({"team": "vision"}),
        create_input_entry("s3://data/train.csv", name="train", digest="sha256:ab"),
    ], name="first", run_state=finished)
    _write_run(app_layout, "0.0.2", [_metrics(_T0, {"acc": 0.7})], parent="0.0.1")


def _read(app_layout, **kwargs):
    return runs_dataframe(app_layout.app_name, storage=_storage(app_layout), **kwargs)


# ---------------------------------------------------------------------------
# flattening (no pandas needed)
# ---------------------------------------------------------------------------


def test_run_record_flattens_a_row_mlflow_style():
    row = {
        "verstr": "0.0.1", "idx": 1, "name": "first", "status": "succeeded",
        "kind": "outer", "parent": None, "timestamp": _T0, "started_at": _T0,
        "finished_at": None, "metrics": {"loss": 0.4}, "params": {"model": "xgb"},
        "tags": {"team": "vision"},
        "inputs": {"train": {"uri": "s3://d/train.csv", "digest": None}},
    }
    record = frames.run_record(row)

    assert record["run_id"] == "0.0.1"
    assert record["name"] == "first"
    assert record["status"] == "succeeded"
    assert record["kind"] == "outer"
    assert record["metrics.loss"] == 0.4
    assert record["params.model"] == "xgb"
    assert record["tags.team"] == "vision"
    assert record["inputs.train"] == "s3://d/train.csv"
    assert record["timestamp"] == datetime.datetime(
        2026, 9, 21, 12, 0, 1, tzinfo=datetime.timezone.utc
    )
    assert record["finished_at"] is None
    assert not [k for k, v in record.items() if isinstance(v, dict)]


def test_run_columns_lead_and_the_rest_are_sorted_by_prefix():
    records = [
        {"run_id": "a", "params.b": 1, "metrics.z": 1, "tags.t": "x"},
        {"run_id": "b", "metrics.a": 2, "inputs.i": "u", "params.a": 3},
    ]
    columns = frames.run_columns(records)

    assert columns[: len(frames.LEADING_COLUMNS)] == list(frames.LEADING_COLUMNS)
    assert columns[len(frames.LEADING_COLUMNS):] == [
        "metrics.a", "metrics.z", "params.a", "params.b", "tags.t", "inputs.i",
    ]


def test_history_records_are_step_timestamp_value():
    points = [{"step": 0, "ts": _T0, "value": 0.9}, {"step": None, "ts": _T1, "value": 0.4}]
    records = frames.history_records(points)

    assert [r["step"] for r in records] == [0, None]
    assert [r["value"] for r in records] == [0.9, 0.4]
    assert records[0]["timestamp"].tzinfo is not None


def test_missing_pandas_names_the_extra(monkeypatch):
    real_import = builtins.__import__

    def _no_pandas(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise ImportError("No module named 'pandas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pandas)
    with pytest.raises(ImportError, match=r"vmn-exp-sdk\[pandas\]"):
        frames.require_pandas()


def test_pandas_is_an_optional_extra_of_the_sdk():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "packages", "vmn-exp-sdk", "pyproject.toml")
    with open(path) as f:
        text = f.read()
    deps = text.split("[project.optional-dependencies]")[0]
    assert "pandas" not in deps
    assert "\npandas = [" in text


# ---------------------------------------------------------------------------
# DataFrames
# ---------------------------------------------------------------------------


def test_runs_dataframe_one_row_per_run(app_layout):
    pd = pytest.importorskip("pandas")
    _seed(app_layout)
    df = _read(app_layout)

    assert isinstance(df, pd.DataFrame)
    assert list(df["run_id"]) == ["0.0.1", "0.0.2"]
    first = df.set_index("run_id").loc["0.0.1"]
    assert first["name"] == "first"
    assert first["status"] == "succeeded"
    assert first["kind"] == "outer"
    assert first["metrics.loss"] == 0.4
    assert first["params.model"] == "xgb"
    assert first["tags.team"] == "vision"
    assert first["inputs.train"] == "s3://data/train.csv"
    assert first["duration_sec"] == 1.5
    second = df.set_index("run_id").loc["0.0.2"]
    assert second["parent"] == "0.0.1"
    assert second["kind"] == "inner"
    assert pd.isna(second["metrics.loss"])
    assert str(df["timestamp"].dtype).startswith("datetime64")


def test_runs_dataframe_passes_query_through(app_layout):
    pytest.importorskip("pandas")
    _seed(app_layout)
    df = _read(app_layout, query="metrics.acc > 0.5")
    assert list(df["run_id"]) == ["0.0.2"]


def test_runs_dataframe_empty_keeps_the_leading_columns(app_layout):
    pytest.importorskip("pandas")
    _seed(app_layout)
    df = _read(app_layout, query="metrics.acc > 5")
    assert df.empty
    assert list(df.columns) == list(frames.LEADING_COLUMNS)


def test_get_metric_history(app_layout):
    pd = pytest.importorskip("pandas")
    _seed(app_layout)
    df = get_metric_history(
        "loss", app_layout.app_name, "0.0.1", storage=_storage(app_layout)
    )

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["step", "timestamp", "value"]
    assert list(df["step"]) == [0, 1]
    assert list(df["value"]) == [0.9, 0.4]


def test_get_metric_history_of_an_unknown_metric_is_empty(app_layout):
    pytest.importorskip("pandas")
    _seed(app_layout)
    df = get_metric_history(
        "nope", app_layout.app_name, "0.0.1", storage=_storage(app_layout)
    )
    assert df.empty
    assert list(df.columns) == ["step", "timestamp", "value"]
