"""Readers honour a run's record format version: a record written by a newer
format is skipped with a warning; a record with none reads as version 1."""
import logging

import pytest

from vmn_exp.core import index as experiment_index
from vmn_exp.core.record_format import RECORD_FORMAT_VERSION, record_format_version
from vmn_exp.core.writer import append_to_log, create_log_entry, create_run
from vmn_exp.sdk.reader import get_run, list_runs
from vmn_exp.storage.local import LocalSnapshotStorage

FUTURE = RECORD_FORMAT_VERSION + 1


@pytest.fixture
def warnings():
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collect(level=logging.WARNING)
    logger = logging.getLogger("vmn")
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _run(storage, code="0.0.1", **meta_updates):
    verstr = create_run(storage, "app", code, {"timestamp": "2026-01-01T00:00:00Z"}, {})
    append_to_log(storage, "app", verstr, create_log_entry("metrics", values={"m": 1}))
    if meta_updates:
        assert storage.update_metadata("app", verstr, meta_updates)
    return verstr


def test_a_missing_format_version_reads_as_1():
    assert record_format_version({"verstr": "v"}) == 1
    assert record_format_version({"verstr": "v", "format_version": 3}) == 3


@pytest.mark.parametrize("use_index", [True, False])
def test_list_runs_skips_a_future_format_record_with_a_warning(
    tmp_path, warnings, use_index
):
    storage = _storage(tmp_path)
    current = _run(storage, "0.0.1")
    future = _run(storage, "0.0.2", format_version=FUTURE)

    rows = list_runs("app", storage=storage, use_index=use_index)

    assert [r["verstr"] for r in rows] == [current]
    assert any(future in w and str(FUTURE) in w for w in warnings), warnings


@pytest.mark.parametrize("use_index", [True, False])
def test_list_runs_reads_a_record_without_a_format_version(tmp_path, use_index):
    storage = _storage(tmp_path)
    legacy = _run(storage, format_version=None)
    assert "format_version" not in storage.load_metadata("app", legacy)

    rows = list_runs("app", storage=storage, use_index=use_index)

    assert [r["verstr"] for r in rows] == [legacy]
    assert rows[0]["metrics"]["m"] == 1


def test_the_index_snapshot_leaves_a_future_record_out(tmp_path, warnings):
    storage = _storage(tmp_path)
    current = _run(storage, "0.0.1")
    _run(storage, "0.0.2", format_version=FUTURE)

    snapshot = experiment_index.indexed_snapshot(storage, "app", wait=True)

    assert snapshot.row(current) is not None
    assert [r["verstr"] for r in snapshot.rows] == [current]
    assert warnings


def test_get_run_exposes_the_format_version(tmp_path):
    storage = _storage(tmp_path)
    verstr = _run(storage)
    assert get_run("app", verstr, storage=storage)["format_version"] == RECORD_FORMAT_VERSION


def test_get_run_reads_a_missing_format_version_as_1(tmp_path):
    storage = _storage(tmp_path)
    verstr = _run(storage, format_version=None)
    assert get_run("app", verstr, storage=storage)["format_version"] == 1


def test_get_run_refuses_a_future_format_record(tmp_path):
    storage = _storage(tmp_path)
    verstr = _run(storage, format_version=FUTURE)
    with pytest.raises(ValueError):
        get_run("app", verstr, storage=storage)


def test_the_registry_skips_a_future_format_version_record(tmp_path, warnings):
    from vmn_exp.registry.names import REGISTRY_APP, version_record_name
    from vmn_exp.registry.store import ensure_model, get_version, register_version

    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "app", "verstr": "0.0.1"})
    assert get_version(storage, "resnet", n)["n"] == n

    name = version_record_name("resnet", n)
    meta, _ = storage.load(REGISTRY_APP, name)
    storage.save(REGISTRY_APP, name, dict(meta, format_version=FUTURE), {})

    assert get_version(storage, "resnet", n) is None
    assert warnings


def test_show_json_exposes_the_format_version(app_layout, capfd):
    import json

    from helpers import _bootstrap, _experiment

    _bootstrap(app_layout)
    assert _experiment(app_layout.app_name) == 0
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", extra_args=["--json"]) == 0
    out = capfd.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["format_version"] == RECORD_FORMAT_VERSION
