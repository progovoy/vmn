"""``vmn-exp push`` ships a run's metric objects (plan 12): the compacted
``metrics/<w>.vmx``, or the ``metrics/<w>.vms`` stream of a run that never
compacted, so the remote run reads back the same series and summaries."""
import time

import pytest
from exp_helpers import _bootstrap, _exp
from s3_helpers import BUCKET, PREFIX, mocked_bucket, s3_storage

from vmn_exp.core import writer
from vmn_exp.core.metric_files import is_indexed_file, is_stream_file
from vmn_exp.sdk import reader
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.uri import s3_uri

URI = s3_uri(BUCKET, PREFIX)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXP_OFFLINE",
                "VMN_SNAPSHOT_METADATA", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(writer, "_WRITER_ID", None)
    with mocked_bucket(monkeypatch):
        yield


@pytest.fixture
def offline(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_EXP_OFFLINE", "1")
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", URI)
    return app_layout


def _run(app_layout, steps=range(5), run_id=None):
    from vmn_exp.sdk import start_run

    with start_run(app_layout.app_name, run_id=run_id) as run:
        for i in steps:
            run.log_metrics({"loss": 1.0 / (i + 1), "acc": i * 0.1}, step=i)
    return run.id


def _push(app_layout, *args):
    return _exp(app_layout.app_name, action="push", extra_args=list(args))


def _local(app_layout):
    return LocalSnapshotStorage(local_store_root(app_layout.repo_path), area="runs")


def _metric_names(storage, app, verstr):
    objects = storage.metric_objects(app, verstr)
    return sorted(name for names in objects.values() for name, _ in names)


def _metric_sizes(storage, app, verstr):
    objects = storage.metric_objects(app, verstr)
    return dict(pair for names in objects.values() for pair in names)


def _view(app, verstr, storage):
    run = reader.get_run(app, verstr, storage=storage)
    return run["metrics"], run.get("metric_summary"), run["series"]


def _assert_same_run(app_layout, verstr):
    app = app_layout.app_name
    local = _view(app, verstr, _local(app_layout))
    assert local[2]["loss"]  # the series is really there
    assert _view(app, verstr, s3_storage()) == local


def test_push_ships_compacted_metrics(offline):
    verstr = _run(offline)
    local_files = _metric_names(_local(offline), offline.app_name, verstr)
    assert local_files and all(is_indexed_file(n) for n in local_files)
    assert _push(offline) == 0
    assert _metric_names(s3_storage(), offline.app_name, verstr) == local_files
    _assert_same_run(offline, verstr)


def test_push_ships_uncompacted_stream(offline, monkeypatch):
    from vmn_exp.sdk import run as run_module

    monkeypatch.setattr(run_module, "compact_by", lambda *a, **k: None)
    verstr = _run(offline)
    local_files = _metric_names(_local(offline), offline.app_name, verstr)
    assert local_files and all(is_stream_file(n) for n in local_files)
    assert _push(offline) == 0
    _assert_same_run(offline, verstr)


def test_repush_of_metrics_is_up_to_date(offline, capfd):
    verstr = _run(offline)
    assert _push(offline) == 0
    capfd.readouterr()
    assert _push(offline) == 0
    lines = capfd.readouterr().out.strip().splitlines()
    assert f"{verstr}  up-to-date" in lines


def test_resumed_run_reuploads_changed_vmx(offline):
    app = offline.app_name
    verstr = _run(offline)
    assert _push(offline) == 0
    before = _metric_sizes(s3_storage(), app, verstr)
    _run(offline, steps=range(5, 10), run_id=verstr)
    assert _push(offline) == 0
    after = _metric_sizes(s3_storage(), app, verstr)
    vmx = [n for n in after if is_indexed_file(n)]
    assert vmx and any(before.get(n) != after[n] for n in vmx)
    assert after == _metric_sizes(_local(offline), app, verstr)
    assert _metric_names(s3_storage(), app, verstr) == _metric_names(
        _local(offline), app, verstr)
    _assert_same_run(offline, verstr)
    assert len(reader.get_run(app, verstr, storage=s3_storage())["series"]["loss"]) == 10


def test_stream_pushed_then_compacted_leaves_no_stale_stream(offline, monkeypatch):
    from s3_helpers import raw_keys

    from vmn_exp.core.metric_compact import compact_by
    from vmn_exp.core.writer import get_writer_id
    from vmn_exp.sdk import run as run_module

    monkeypatch.setattr(run_module, "compact_by", lambda *a, **k: None)
    verstr = _run(offline)
    assert _push(offline) == 0
    compact_by(_local(offline), offline.app_name, verstr, get_writer_id(), time.monotonic() + 30)
    assert _push(offline) == 0
    metric_keys = [k.rsplit("/", 2)[-2:] for k in raw_keys() if "/metrics/" in k]
    assert metric_keys and all(name.endswith(".vmx") for _, name in metric_keys)
    _assert_same_run(offline, verstr)
