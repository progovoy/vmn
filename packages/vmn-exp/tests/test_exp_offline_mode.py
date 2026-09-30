"""VMN_EXP_OFFLINE=1: every storage factory drops the remote and records to
the local root only; offline runs carry the writer id in their name."""
import os

import pytest
from exp_helpers import _bootstrap
from s3_helpers import BUCKET, PREFIX, mocked_bucket, raw_keys

from vmn_exp.core import writer
from vmn_exp.core.storage_resolve import (
    _get_experiment_storage,
    resolve_experiment_storage,
)
from vmn_exp.core.writer import allocate_run_verstr
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.uri import s3_uri

URI = s3_uri(BUCKET, PREFIX)
CODE = "0.0.1-dev.abc1234.0000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXP_OFFLINE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(writer, "_WRITER_ID", None)
    with mocked_bucket(monkeypatch):
        yield


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("VMN_EXP_OFFLINE", "1")


def test_offline_drops_store_uri_from_cli_storage(tmp_path, offline):
    storage = _get_experiment_storage(
        None, {"store": URI, "experiment_dir": str(tmp_path)}
    )
    assert not storage.is_remote()


def test_offline_drops_bucket_shorthand_from_cli_storage(tmp_path, offline):
    params = {"bucket": BUCKET, "prefix": PREFIX, "endpoint_url": "http://x:1",
              "experiment_dir": str(tmp_path)}
    assert not _get_experiment_storage(None, params).is_remote()


def test_offline_drops_remote_from_resolve_experiment_storage(tmp_path, offline):
    assert not resolve_experiment_storage(dir=str(tmp_path), store=URI).is_remote()


def test_offline_without_local_root_raises(offline):
    with pytest.raises(ValueError, match="VMN_EXPERIMENT_DIR"):
        resolve_experiment_storage(store=URI, repo_root=False)


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_offline_false_values_keep_remote(tmp_path, monkeypatch, value):
    monkeypatch.setenv("VMN_EXP_OFFLINE", value)
    assert resolve_experiment_storage(dir=str(tmp_path), store=URI).is_remote()


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_offline_true_values_drop_remote(tmp_path, monkeypatch, value):
    monkeypatch.setenv("VMN_EXP_OFFLINE", value)
    assert not resolve_experiment_storage(dir=str(tmp_path), store=URI).is_remote()


def _dirty(app_layout):
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "committed")
    for name, content in (("tracked.txt", "dirty"), ("untracked.txt", "new")):
        with open(os.path.join(app_layout.repo_path, name), "w") as f:
            f.write(content)


def test_offline_sdk_start_run_with_unreachable_store_records_locally(
    app_layout, monkeypatch, offline
):
    from vmn_exp.sdk import start_run

    _bootstrap(app_layout)
    monkeypatch.setenv(
        "VMN_EXPERIMENT_STORE", s3_uri("unreachable", "p", "http://127.0.0.1:9")
    )
    with start_run(app_layout.app_name) as run:
        run.log_metric("loss", 1.0)
    local = LocalSnapshotStorage(app_layout.repo_path, subdir="experiments")
    assert local.exists(app_layout.app_name, run.id)
    assert run.id.endswith("." + writer.get_writer_id())


def test_offline_code_object_stays_local(app_layout, monkeypatch, offline):
    from vmn_exp.core.code_store import code_app
    from vmn_exp.sdk import start_run

    _bootstrap(app_layout)
    _dirty(app_layout)
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", URI)
    with start_run(app_layout.app_name) as run:
        pass
    local = LocalSnapshotStorage(app_layout.repo_path, subdir="experiments")
    meta = local.load_metadata(app_layout.app_name, run.id)
    assert local.exists(code_app(app_layout.app_name), meta["code"])
    assert raw_keys() == []


def _claim_run(storage, suffix_kw):
    def make_record(verstr):
        return {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {}

    return allocate_run_verstr(storage, "app", CODE, make_record=make_record,
                               **suffix_kw)


def test_offline_run_names_carry_writer_suffix(tmp_path, monkeypatch, offline):
    monkeypatch.setenv("HOSTNAME", "laptop")
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    names = [_claim_run(local, {}) for _ in range(2)]
    assert names == [f"{CODE}.laptop", f"{CODE}.laptop.2"]


def test_allocate_suffix_none_ignores_writer_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "pod1")
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    names = [_claim_run(local, {"suffix": None}) for _ in range(2)]
    assert names == [CODE, f"{CODE}.r2"]


def test_allocate_explicit_suffix(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    names = [_claim_run(local, {"suffix": "w1"}) for _ in range(2)]
    assert names == [f"{CODE}.w1", f"{CODE}.w1.2"]


def test_online_default_keeps_writer_env_suffix(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "pod1")
    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    assert _claim_run(local, {}) == f"{CODE}.pod1"
