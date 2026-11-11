"""Plan 40 C6: a kept log buffer, and an SDK run whose final upload from a
log buffer failed, point at ``vmn-exp buffers ship``."""
import logging

import pytest
from buffer_recover_fakes import APP, V, kept_buffer
from deferred_ship_fakes import FakeBucket
from s3_helpers import meta

from vmn_exp.sdk.run import Run
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.core.real_io import RealRandom

HINT = "ship it later with: vmn-exp buffers ship"


@pytest.fixture(autouse=True)
def _flush_at_end():
    yield
    buffered.close_all()


@pytest.fixture
def bucket(tmp_path):
    remote = FakeBucket(str(tmp_path / "bucket"))
    remote.events = []
    remote.save(APP, V, meta(V), {})
    return remote


def test_the_kept_buffer_warning_names_buffers_ship(monkeypatch, tmp_path, bucket, caplog):
    with caplog.at_level(logging.WARNING):
        root = kept_buffer(monkeypatch, bucket, str(tmp_path / "base"))

    (warning,) = [r.getMessage() for r in caplog.records if root in r.getMessage()]
    assert warning.endswith(HINT)


def test_a_log_buffer_runs_failed_final_upload_names_buffers_ship(tmp_path, bucket):
    storage = BufferedRemoteStorage(bucket, str(tmp_path / "base"), area="runs")
    run = Run(storage, APP, V, 3600, random=RealRandom())

    assert run._not_uploaded("state", OSError("bucket down")).endswith(f"bucket down; {HINT}")


def test_a_local_first_runs_failed_final_upload_does_not(tmp_path, bucket):
    local = LocalSnapshotStorage(str(tmp_path / "local"), "runs")
    run = Run(CachedSnapshotStorage(local, bucket), APP, V, 3600, random=RealRandom())

    assert HINT not in run._not_uploaded("state", OSError("bucket down"))
