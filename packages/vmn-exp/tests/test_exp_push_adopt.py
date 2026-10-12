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
