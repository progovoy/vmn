"""The local-only write guard on GCS and Azure (same cache wrapper as S3), and
on an SDK resume of a run recorded without a remote."""
import pytest
from exp_helpers import _bootstrap, _storage

from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions
from vmn_exp.core.manage import tag_run
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.writer import save_artifact, save_run_state
from vmn_exp.sdk import start_run
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.areas import local_store_root

APP = "app"
X = "0.0.1-dev.abc1234.0000001"


def _gcs():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    return GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())


def _azure():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    return AzureSnapshotStorage(
        "bkt", prefix="p", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


def _meta(timestamp="2026-01-01T00:00:00Z"):
    return {"verstr": X, "timestamp": timestamp}


def _write_everything(host, tmp_path):
    assert tag_run(host, APP, X, tags={"k": "v"})
    save_run_state(host, APP, X, {"state": "finished", "exit_code": 0})
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")
    save_artifact(host, APP, X, str(artifact))


@pytest.mark.parametrize("make_remote", [_gcs, _azure], ids=["gs", "az"])
@pytest.mark.parametrize("remote_has", [None, "foreign"])
def test_guard_applies_to_gcs_and_azure_backends(tmp_path, make_remote, remote_has):
    remote = make_remote()
    if remote_has:
        remote.save(APP, X, _meta("2026-09-09T00:00:00Z"), {})
    local = LocalSnapshotStorage(str(tmp_path / "root"), area="runs")
    local.save(APP, X, _meta(), {})
    host = CachedSnapshotStorage(local, remote)

    _write_everything(host, tmp_path)

    assert remote.load_file(APP, X, RUN_STATE_FILE) is None
    assert remote.list_artifacts(APP, X) == []
    assert remote.load_merged_log(APP, X) == []
    assert local.load_file(APP, X, RUN_STATE_FILE)


@pytest.mark.parametrize("make_remote", [_gcs, _azure], ids=["gs", "az"])
def test_gcs_and_azure_records_on_the_remote_are_written_through(tmp_path, make_remote):
    remote = make_remote()
    remote.save(APP, X, _meta(), {})
    host = CachedSnapshotStorage(
        LocalSnapshotStorage(str(tmp_path / "root"), area="runs"), remote
    )

    _write_everything(host, tmp_path)

    assert remote.load_file(APP, X, RUN_STATE_FILE)
    assert [a["name"] for a in remote.list_artifacts(APP, X)] == ["artifacts/model.bin"]
    assert any(e["type"] == "tags" for e in remote.load_merged_log(APP, X))


@pytest.fixture
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


def test_sdk_resume_of_local_only_run_writes_nothing_to_remote(
    app_layout, tmp_path, _clean_env
):
    _bootstrap(app_layout)
    first = start_run(app_layout.app_name, storage=_storage(app_layout))
    first.log_metric("loss", 1.0, step=1)
    first.finish(exit_code=143)

    remote = _gcs()
    online = CachedSnapshotStorage(
        LocalSnapshotStorage(local_store_root(app_layout.repo_path), area="runs"), remote
    )
    resumed = start_run(
        app_layout.app_name, run_id=first.id, storage=online, heartbeat_interval_sec=0.05
    )
    resumed.log_metric("loss", 0.5, step=2)
    resumed.set_tag("resumed", "yes")
    resumed.finish(exit_code=0)

    assert remote.list_files(app_layout.app_name) == {}
    assert remote.load_file(app_layout.app_name, first.id, RUN_STATE_FILE) is None
    assert remote.load_merged_log(app_layout.app_name, first.id) == []
