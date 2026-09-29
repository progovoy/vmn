"""``--store <uri>`` on every command that opens experiment/snapshot storage:
``exp`` (and ``import-mlflow``), ``model`` and ``ui``."""
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from version_stamp.cli.args import parse_user_commands

BUCKET = "flags-bkt"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET",
                "VMN_EXPERIMENT_PREFIX", "VMN_EXPERIMENT_ENDPOINT_URL",
                "VMN_EXPERIMENT_DIR"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def s3(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _remote(storage):
    return getattr(storage, "_remote", storage)


@pytest.mark.parametrize("argv", [
    ["exp", "list", "app"],
    ["exp", "import-mlflow", "app", "--mlruns", "/x"],
    ["ui"],
])
def test_store_flag_parses(argv):
    args = parse_user_commands(argv + ["--store", "gs://b/p"])
    assert args.store == "gs://b/p"


def test_snapshot_storage_honours_store(s3, tmp_path):
    from vmn_exp.snapshot import _get_storage

    vcs = SimpleNamespace(vmn_root_path=str(tmp_path))
    storage = _get_storage(vcs, {"store": f"s3://{BUCKET}/snaps"})
    assert (_remote(storage).bucket, _remote(storage).prefix) == (BUCKET, "snaps")


def test_snapshot_storage_bucket_shorthand_keeps_its_prefix(s3, tmp_path):
    from vmn_exp.snapshot import _get_storage

    vcs = SimpleNamespace(vmn_root_path=str(tmp_path))
    storage = _get_storage(vcs, {"bucket": BUCKET})
    assert _remote(storage).prefix == "vmn-snapshots"


def test_model_storage_honours_store(s3):
    from vmn_exp.registry.cli import _get_storage

    args = SimpleNamespace(dir=None, store=f"s3://{BUCKET}/models",
                           bucket=None, prefix=None, endpoint_url=None)
    assert _remote(_get_storage(args)).prefix == "models"


def test_import_mlflow_storage_honours_store(s3):
    from vmn_exp.importers.cli import _get_storage

    args = SimpleNamespace(experiment_dir=None, store=f"s3://{BUCKET}/imp",
                           bucket=None, prefix=None, endpoint_url=None)
    assert _remote(_get_storage(args)).prefix == "imp"


def test_ui_store_flag_adds_a_store_workspace(tmp_path, s3):
    pytest.importorskip("fastapi")
    from vmn_exp.ui.cli import build_manager
    from vmn_exp.ui.workspaces import workspace_storage

    args = parse_user_commands(
        ["ui", "--data-dir", str(tmp_path / "d"), "--store", f"s3://{BUCKET}/team"]
    )
    manager = build_manager(args)
    stores = [w for w in manager.list() if w.kind == "store"]
    assert [w.store for w in stores] == [f"s3://{BUCKET}/team"]
    assert _remote(workspace_storage(stores[0])).prefix == "team"

    again = build_manager(args)  # re-attaching is a no-op
    assert len([w for w in again.list() if w.kind == "store"]) == 1


def test_ui_workspace_storage_is_only_for_store_workspaces():
    from vmn_exp.ui.workspaces import Workspace, workspace_storage

    assert workspace_storage(Workspace(name="g", kind="git", path="/x")) is None


def test_ui_store_workspaces_get_their_own_index(tmp_path):
    pytest.importorskip("fastapi")
    from vmn_exp.ui.index import s3_cache_path
    from vmn_exp.ui.workspaces import Workspace

    a = Workspace(name="a", kind="store", store="gs://b/one")
    b = Workspace(name="b", kind="store", store="gs://b/two")
    assert s3_cache_path(str(tmp_path), a) != s3_cache_path(str(tmp_path), b)
