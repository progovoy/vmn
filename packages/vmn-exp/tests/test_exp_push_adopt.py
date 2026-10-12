"""``vmn-exp push --adopt``: a run whose record was copied or moved across
filesystems holds streams of another owner, which push leaves alone (noting
it on stderr); ``--adopt`` makes this checkout their owner and pushes them."""
import shutil

import pytest
from exp_helpers import _bootstrap, _exp
from s3_helpers import BUCKET, PREFIX, mocked_bucket, s3_storage
from vmn_exp.core import writer
from vmn_exp.core.series_reader import SeriesReader
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


def _moved_run(app_layout, tmp_path):
    """A finished offline run whose record was moved across filesystems."""
    from vmn_exp.sdk import start_run

    with start_run(app_layout.app_name) as run:
        run.log_metric("loss", 0.5)
    record = LocalSnapshotStorage(local_store_root(app_layout.repo_path), area="runs") \
        .local_record_dir(app_layout.app_name, run.id)
    shutil.copytree(record, tmp_path / "away")
    shutil.rmtree(record)
    shutil.copytree(tmp_path / "away", record)
    return run.id


def _remote_loss(app_name, verstr):
    reader = SeriesReader.from_storage(s3_storage(), app_name, verstr, rewinds=())
    return list(reader.points("loss").values)


def _push(app_layout, *args):
    return _exp(app_layout.app_name, action="push", extra_args=list(args))


def test_push_notes_inherited_streams_and_adopt_pushes_them(offline, tmp_path, capfd):
    verstr = _moved_run(offline, tmp_path)
    capfd.readouterr()

    assert _push(offline) == 0
    err = capfd.readouterr().err
    assert verstr in err and "--adopt" in err
    assert _remote_loss(offline.app_name, verstr) == []

    assert _push(offline, "--adopt") == 0
    assert "--adopt" not in capfd.readouterr().err
    assert _remote_loss(offline.app_name, verstr) == [0.5]


def _shrink_remote_vmx(app_name, verstr, tmp_path):
    """Replace the remote ``.vmx`` of the run's stream by one holding only its
    first point: what another clone's compaction of a partial ship builds."""
    from vmn_exp.core.metric_columns import Columns
    from vmn_exp.core.metric_index_file import build_index

    remote = s3_storage()
    (stream,) = remote.metric_objects(app_name, verstr)
    path = tmp_path / "foreign.vmx"
    path.write_bytes(build_index(stream, {"loss": Columns([0], [1], [0.5])}))
    assert remote.put_indexed(app_name, verstr, stream, str(path), replace=True)


def _run_logging(app_layout, *values):
    from vmn_exp.sdk import start_run

    with start_run(app_layout.app_name) as run:
        for step, value in enumerate(values):
            run.log_metric("loss", value, step=step)
    return run.id


def _move_record(app_layout, verstr, away):
    record = LocalSnapshotStorage(local_store_root(app_layout.repo_path), area="runs") \
        .local_record_dir(app_layout.app_name, verstr)
    shutil.copytree(record, away)
    shutil.rmtree(record)
    shutil.copytree(away, record)


def test_push_adopt_refuses_a_run_whose_remote_vmx_lacks_local_points(offline, tmp_path, capfd):
    lacking = _run_logging(offline, 0.5, 0.25)
    assert _push(offline) == 0
    _shrink_remote_vmx(offline.app_name, lacking, tmp_path)
    _move_record(offline, lacking, tmp_path / "away1")
    other = _moved_run(offline, tmp_path / "o")
    capfd.readouterr()

    assert _push(offline, "--adopt") == 1

    err = capfd.readouterr().err
    assert f"{lacking}: could not adopt" in err and "not adopting" in err
    assert f"{other}: could not adopt" not in err
    assert _remote_loss(offline.app_name, lacking) == [0.5]
    assert _remote_loss(offline.app_name, other) == [0.5]
    local = SeriesReader.from_storage(
        LocalSnapshotStorage(local_store_root(offline.repo_path), area="runs"),
        offline.app_name, lacking, rewinds=())
    assert list(local.points("loss").values) == [0.5, 0.25]
