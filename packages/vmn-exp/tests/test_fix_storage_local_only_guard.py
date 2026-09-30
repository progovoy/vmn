"""A local-first cache writes through to its remote only when the remote holds
*this* record.

A run recorded while no remote was configured (``VMN_EXPERIMENT_DIR`` only, a
run older than ``experiment.storage`` in conf.yml) lives only locally. Writes
to it — tags, run state, alert markers, artifacts, output.log, media, log
lines — must stay local: on the remote they would be orphan objects that the
next host claiming that name inherits, or, when the remote holds a different
run of the same name, writes into that foreign record.
"""
import os

import pytest
import yaml
from s3_helpers import (
    cached_host,
    entry,
    meta,
    mocked_bucket,
    raw_keys,
    record_calls,
    s3_storage,
)

from vmn_exp.core.alerts.transitions import ALERTS_FILE, alert_transition
from vmn_exp.core.manage import tag_run
from vmn_exp.core.output_log import OUTPUT_LOG_NAME, OutputArtifact
from vmn_exp.core.status import FAILED, RUN_STATE_FILE
from vmn_exp.core.writer import append_to_log, flush_log, save_artifact, save_run_state
from vmn_exp.sdk.media_uploads import MediaUploads, staging_dir
from vmn_exp.sdk.state_publisher import RunStatePublisher
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
X = "0.0.1-dev.abc1234.0000001"
FINISHED = {"state": "finished", "exit_code": 1, "finished_at": "2026-01-01T00:01:00Z"}


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _local_only(tmp_path, name="a", **kw):
    """A run recorded under host *name*'s root with no remote configured."""
    local = LocalSnapshotStorage(str(tmp_path / name), subdir="experiments")
    local.save(APP, X, meta(X, **kw), {})
    return cached_host(tmp_path, name)


def _remote_keys_of(verstr):
    return [k for k in raw_keys() if f"/{verstr}/" in k]


def _artifact(tmp_path, name="model.bin", body=b"weights"):
    path = tmp_path / name
    path.write_bytes(body)
    return str(path)


def test_tag_on_local_only_run_writes_nothing_to_remote(tmp_path):
    host = _local_only(tmp_path)
    assert tag_run(host, APP, X, tags={"k": "v"})
    assert _remote_keys_of(X) == []
    assert any(e["type"] == "tags" for e in host.load_merged_log(APP, X))


def test_run_state_on_local_only_run_stays_local(tmp_path):
    host = _local_only(tmp_path)
    save_run_state(host, APP, X, dict(FINISHED))
    assert _remote_keys_of(X) == []
    assert host.load_file(APP, X, RUN_STATE_FILE)


def test_artifact_on_local_only_run_stays_local(tmp_path):
    host = _local_only(tmp_path)
    save_artifact(host, APP, X, _artifact(tmp_path))
    assert _remote_keys_of(X) == []
    assert host.artifact_local_path(APP, X, "model.bin")


def test_output_log_on_local_only_run_stays_local(tmp_path):
    host = _local_only(tmp_path)
    output = OutputArtifact(host, APP, X, cap_bytes=1024)
    output.write(b"hello\n")
    output.seal()
    assert output.upload()
    assert _remote_keys_of(X) == []
    assert host.artifact_local_path(APP, X, OUTPUT_LOG_NAME)


def test_media_upload_on_local_only_run_stays_local(tmp_path):
    host = _local_only(tmp_path)
    stored = []
    uploads = MediaUploads(lambda path, name: save_artifact(host, APP, X, path, name))
    staged = staging_dir()
    image = os.path.join(staged, "plot.png")
    with open(image, "wb") as f:
        f.write(b"png")
    uploads.submit(staged, image, "media/plot.png", lambda: stored.append(True))
    assert uploads.close(10)
    assert stored == [True]
    assert _remote_keys_of(X) == []


class _Delivered:
    def send(self, alert):
        return True


def test_alerts_sent_on_local_only_run_stays_local(tmp_path):
    host = _local_only(tmp_path)
    assert alert_transition(host, APP, X, dict(FINISHED), FAILED, _Delivered())
    assert _remote_keys_of(X) == []
    assert host.load_file(APP, X, ALERTS_FILE)


def test_state_publisher_skips_remote_for_local_only_run(tmp_path):
    host = _local_only(tmp_path)
    publisher = RunStatePublisher(host, APP, X)
    publisher.publish(dict(FINISHED))
    assert publisher.close(10)
    assert _remote_keys_of(X) == []
    assert yaml.safe_load(host.load_file(APP, X, RUN_STATE_FILE))["exit_code"] == 1


def test_state_publisher_still_uploads_a_record_the_remote_holds(tmp_path):
    host = cached_host(tmp_path, "a")
    assert host.create_exclusive(APP, X, meta(X), {})
    publisher = RunStatePublisher(host, APP, X)
    publisher.publish(dict(FINISHED))
    assert publisher.close(10)
    assert s3_storage().load_file(APP, X, RUN_STATE_FILE)


def test_other_host_claim_does_not_inherit_offline_log(tmp_path):
    offline = _local_only(tmp_path, "a")
    append_to_log(offline, APP, X, entry(0))
    flush_log(offline, APP, X)
    save_run_state(offline, APP, X, dict(FINISHED))

    other = cached_host(tmp_path, "b")
    assert other.create_exclusive(APP, X, meta(X, timestamp="2026-02-02T00:00:00Z"), {})
    assert other.load_merged_log(APP, X) == []
    assert other.load_file(APP, X, RUN_STATE_FILE) is None


def test_local_only_run_colliding_with_foreign_remote_record_does_not_write_into_it(
    tmp_path,
):
    foreign = s3_storage()
    foreign.save(APP, X, meta(X, timestamp="2026-05-05T00:00:00Z"), {})
    foreign.save_file(APP, X, RUN_STATE_FILE, "state: running\n")
    before = raw_keys()

    host = _local_only(tmp_path)
    assert tag_run(host, APP, X, tags={"k": "v"})
    save_run_state(host, APP, X, dict(FINISHED))
    save_artifact(host, APP, X, _artifact(tmp_path))
    host.save_file(APP, X, ALERTS_FILE, "sent: {}\n")

    assert raw_keys() == before
    assert foreign.load_file(APP, X, RUN_STATE_FILE) == b"state: running\n"


def test_run_created_through_cache_still_syncs_without_extra_head(tmp_path):
    host = cached_host(tmp_path, "a")
    assert host.create_exclusive(APP, X, meta(X), {})
    calls = record_calls(host._remote._s3)

    assert tag_run(host, APP, X, tags={"k": "v"})

    metadata_reads = [
        op for op, params in calls
        if op in ("GetObject", "HeadObject") and params["Key"].endswith("metadata.yml")
    ]
    assert metadata_reads == []
    assert any(e["type"] == "tags" for e in s3_storage().load_merged_log(APP, X))


def test_record_mirrored_by_an_earlier_process_is_written_through(tmp_path):
    assert cached_host(tmp_path, "a").create_exclusive(APP, X, meta(X), {})

    later = cached_host(tmp_path, "a")  # a new process, same host
    assert tag_run(later, APP, X, tags={"k": "v"})
    assert any(e["type"] == "tags" for e in s3_storage().load_merged_log(APP, X))


def test_remote_only_record_is_still_written_through(tmp_path):
    s3_storage().save(APP, X, meta(X), {})
    host = cached_host(tmp_path, "a")

    assert tag_run(host, APP, X, tags={"k": "v"})
    save_run_state(host, APP, X, dict(FINISHED))

    remote = s3_storage()
    assert any(e["type"] == "tags" for e in remote.load_merged_log(APP, X))
    assert remote.load_file(APP, X, RUN_STATE_FILE)
