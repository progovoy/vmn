"""Every metric writer records into metric streams (plan 12 §2 D1/D6, §4.1).

The JSONL log carries no ``metrics`` entries any more; readers get them back
from the streams (``load_merged_log`` synthesizes them for log views).
"""
import json
import os

from vmn_exp.core.metric_block import decode_blocks
from vmn_exp.core.record_format import RECORD_FORMAT_VERSION
from vmn_exp.core.writer import (
    append_entries_to_log,
    append_to_log,
    create_log_entry,
    flush_log,
    get_writer_id,
)
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
V = "0.0.1-dev.aaaaaaa.bbbbbbb"


def _storage(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), "runs")
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return storage


def _jsonl_types(storage):
    record = storage.local_record_dir(APP, V)
    types = []
    for dirpath, _, files in os.walk(record):
        for name in files:
            if name.endswith(".jsonl"):
                with open(os.path.join(dirpath, name)) as f:
                    types += [json.loads(line)["type"] for line in f if line.strip()]
    return types


def _stream_values(storage, key):
    values = []
    for objects in storage.metric_objects(APP, V).values():
        for name, size in objects:
            for block in decode_blocks(storage.read_range(APP, V, name, 0, size)):
                if key in block.keys:
                    values += list(block.keys[key].values)
    return values


def _merged_metrics(storage):
    return [e for e in storage.load_merged_log(APP, V) if e.get("type") == "metrics"]


def test_record_format_is_version_2():
    assert RECORD_FORMAT_VERSION == 2


def test_append_to_log_sends_metrics_to_the_stream(tmp_path):
    storage = _storage(tmp_path)
    append_to_log(storage, APP, V, create_log_entry("metrics", values={"x": 1.5}, step=3))
    append_to_log(storage, APP, V, create_log_entry("note", text="hi"))
    assert "metrics" not in _jsonl_types(storage)
    assert _stream_values(storage, "x") == [1.5]
    merged = _merged_metrics(storage)
    assert [(e["values"], e["step"]) for e in merged] == [({"x": 1.5}, 3)]


def test_append_entries_to_log_splits_a_mixed_batch(tmp_path):
    storage = _storage(tmp_path)
    entries = [create_log_entry("metrics", values={"a": 1.0, "b": 2.0}, step=0),
               create_log_entry("params", params={"lr": 0.1})]
    assert append_entries_to_log(storage, APP, V, entries)
    assert _jsonl_types(storage) == ["params"]
    assert _merged_metrics(storage)[0]["values"] == {"a": 1.0, "b": 2.0}


def test_flush_log_ships_metric_blocks_too(tmp_path):
    calls = []

    class Spy:
        def sync_log_to_remote(self, *a):
            calls.append("log")

        def sync_metrics_to_remote(self, *a):
            calls.append(("metrics",) + a)

    flush_log(Spy(), APP, V)
    assert calls == ["log", ("metrics", APP, V, get_writer_id())]


def test_sdk_log_metrics_reach_the_stream_not_the_jsonl(tmp_path):
    storage = _storage(tmp_path)
    run = Run(storage, APP, V, 60, system_metrics=False)
    run._open()
    run.log_metrics({"loss": 0.5})
    run.log_metric("loss", 0.25)
    run.finish()
    assert "metrics" not in _jsonl_types(storage)
    merged = _merged_metrics(storage)
    assert [e["values"]["loss"] for e in merged] == [0.5, 0.25]
    assert [e["step"] for e in merged] == [0, 1]


def test_mlflow_import_records_metrics_as_a_stream(tmp_path):
    from mlflow_fixtures import MlflowFixtureBuilder

    from vmn_exp.importers.import_records import import_run, run_verstr
    from vmn_exp.importers.mlflow_filestore import iter_runs

    builder = MlflowFixtureBuilder(tmp_path / "mlruns")
    builder.add_experiment("1", "exp_one")
    run_id = "a" * 36
    builder.add_run("1", run_id, metrics={"loss": [(1700000001000, 0.5, 0)]})
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    import_run(storage, APP, next(iter_runs(tmp_path / "mlruns")))
    verstr = run_verstr(run_id)
    assert storage.metric_objects(APP, verstr)
    log = storage.load_merged_log(APP, verstr)
    assert [e["values"] for e in log if e.get("type") == "metrics"] == [{"loss": 0.5}]


def test_a_fork_copies_points_as_inherited_blocks(tmp_path):
    from vmn_exp.core.fork import seed_fork

    storage = _storage(tmp_path)
    fork = "0.0.1-dev.aaaaaaa.ccccccc"
    storage.save(APP, fork, {"verstr": fork, "timestamp": "2026-01-01T00:00:01Z"}, {})
    for step in range(4):
        append_to_log(storage, APP, V, create_log_entry("metrics", values={"x": step}, step=step))
    assert seed_fork(storage, APP, fork, V, step=1) == {"verstr": V, "step": 1}
    objects = storage.metric_objects(APP, fork)
    (name, size), = next(iter(objects.values()))
    blocks = list(decode_blocks(storage.read_range(APP, fork, name, 0, size)))
    assert [b.inherited for b in blocks] == [True]
    assert list(blocks[0].keys["x"].steps) == [0, 1]
    merged = [e for e in storage.load_merged_log(APP, fork) if e.get("type") == "metrics"]
    assert all(e["inherited"] for e in merged)
