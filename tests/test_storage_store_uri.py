"""Selecting experiment storage by URI: ``--store`` > ``VMN_EXPERIMENT_STORE``
> conf ``experiment.storage.uri``, each beating the ``--bucket`` shorthand."""
import os
from types import SimpleNamespace

import boto3
import pytest
import yaml
from moto import mock_aws

from vmn_exp.core.storage_resolve import resolve_experiment_storage
from vmn_exp.core.writer import merge_conf_into_params, merge_env_into_params
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.s3 import S3SnapshotStorage

BUCKET = "ml-exps"
APP = "trainer"
VERSTR = "1.2.0-dev.abc1234.0000000"
ENV_KEYS = (
    "VMN_EXPERIMENT_STORE",
    "VMN_EXPERIMENT_BUCKET",
    "VMN_EXPERIMENT_PREFIX",
    "VMN_EXPERIMENT_ENDPOINT_URL",
    "VMN_EXPERIMENT_DIR",
    "VMN_SNAPSHOT_METADATA",
    "VMN_EXPERIMENT_ID",
    "VMN_APP_NAME",
    "VMN_WRITER_ID",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def s3(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1"
    ).items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _keys(client, prefix=""):
    listed = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [o["Key"] for o in listed.get("Contents", [])]


def _record(storage):
    return storage.create_exclusive(APP, VERSTR, {"verstr": VERSTR, "app": APP}, {})


def _remote(storage):
    return getattr(storage, "_remote", storage)


# -- open_storage ---------------------------------------------------------------


def test_s3_uri_without_a_root_writes_to_its_prefix(s3):
    storage = open_storage(f"s3://{BUCKET}/team/exps", subdir="experiments")
    assert _record(storage)
    assert _keys(s3, "team/exps/trainer/")


def test_s3_uri_without_a_prefix_uses_the_subdir_default(s3):
    storage = open_storage(f"s3://{BUCKET}", subdir="experiments")
    assert _remote(storage).prefix == "vmn-experiments"


def test_s3_uri_with_a_root_is_cached_locally(s3, tmp_path):
    storage = open_storage(
        f"s3://{BUCKET}/p", vmn_root_path=str(tmp_path), subdir="experiments"
    )
    assert _record(storage)
    assert isinstance(storage._remote, S3SnapshotStorage)
    assert (tmp_path / ".vmn" / APP / "experiments").is_dir()
    assert _keys(s3, "p/trainer/")


def test_endpoint_url_option_reaches_the_s3_client(s3):
    storage = open_storage(
        f"s3://{BUCKET}/p?endpoint_url=http://localhost:1", subdir="experiments"
    )
    assert _remote(storage).endpoint_url == "http://localhost:1"


def test_file_uri_is_the_local_root(tmp_path):
    other = tmp_path / "repo"
    storage = open_storage(
        f"file://{tmp_path / 'nfs'}", vmn_root_path=str(other), subdir="experiments"
    )
    assert _record(storage)
    assert (tmp_path / "nfs" / ".vmn" / APP / "experiments").is_dir()
    assert not other.exists()


def test_no_root_and_no_store_is_an_error():
    with pytest.raises(ValueError):
        open_storage(None, subdir="experiments")


# -- resolution order -------------------------------------------------------------


def test_resolve_takes_a_store_uri(s3):
    storage = resolve_experiment_storage(store=f"s3://{BUCKET}/r", repo_root=False)
    assert _record(storage)
    assert _keys(s3, "r/")


def test_store_env_selects_the_store(s3, monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", f"s3://{BUCKET}/from-env")
    assert _record(resolve_experiment_storage(repo_root=False))
    assert _keys(s3, "from-env/")


def test_store_beats_the_bucket_shorthand(s3, monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", "some-other-bucket")
    storage = resolve_experiment_storage(store=f"s3://{BUCKET}/win", repo_root=False)
    assert _remote(storage).bucket == BUCKET


def test_env_store_fills_params():
    os.environ["VMN_EXPERIMENT_STORE"] = "gs://b/p"
    try:
        params = {"store": None}
        merge_env_into_params(params)
        assert params["store"] == "gs://b/p"
    finally:
        del os.environ["VMN_EXPERIMENT_STORE"]


def test_conf_storage_uri_fills_params():
    vcs = SimpleNamespace(experiment={"storage": {"uri": "az://c/p"}})
    params = {"store": None}
    merge_conf_into_params(vcs, params)
    assert params["store"] == "az://c/p"


def test_store_flag_beats_conf_uri():
    vcs = SimpleNamespace(experiment={"storage": {"uri": "az://c/p"}})
    params = {"store": "gs://flag/p"}
    merge_conf_into_params(vcs, params)
    assert params["store"] == "gs://flag/p"


# -- CLI and SDK -----------------------------------------------------------------


def _container(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {"verstr": VERSTR, "app_name": APP,
             "base_version": "1.2.0", "base_commit": "abc1234"}
        )
    )
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))


def test_cli_store_flag_records_to_the_uri(tmp_path, monkeypatch, s3):
    from vmn_exp.cli.main import vmn_exp_run

    _container(tmp_path, monkeypatch)
    err, _ = vmn_exp_run(["exp", "create", APP, "--store", f"s3://{BUCKET}/cli"])

    assert err == 0
    assert _keys(s3, "cli/trainer/")


def test_cli_file_store_records_to_the_path(tmp_path, monkeypatch):
    from vmn_exp.cli.main import vmn_exp_run

    _container(tmp_path, monkeypatch)
    err, _ = vmn_exp_run(["exp", "create", APP, "--store", f"file://{tmp_path / 'd'}"])

    assert err == 0
    assert (tmp_path / "d" / ".vmn" / APP / "experiments").is_dir()


def test_start_run_in_a_pod_records_to_the_env_store(tmp_path, monkeypatch, s3):
    from vmn_exp.sdk import start_run

    _container(tmp_path, monkeypatch)
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", f"s3://{BUCKET}/pod")

    with start_run() as run:
        run.log_metric("loss", 0.5)

    assert any(k.startswith(f"pod/trainer/") for k in _keys(s3))
    assert run.id
