"""Experiment storage can be pointed at a bucket through the environment.

A pod has no conf.yml and often no git checkout: ``VMN_EXPERIMENT_BUCKET`` /
``VMN_EXPERIMENT_PREFIX`` / ``VMN_EXPERIMENT_ENDPOINT_URL`` let both the CLI and
``start_run()`` record straight to S3.
"""
import os
from types import SimpleNamespace

import boto3
import pytest
import yaml
from moto import mock_aws

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core.experiment_writer import (
    merge_conf_into_params,
    merge_env_into_params,
)
from version_stamp.exp import start_run

BUCKET = "ml-exps"
ENV_KEYS = (
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


def test_env_fills_unset_storage_params(monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", BUCKET)
    monkeypatch.setenv("VMN_EXPERIMENT_PREFIX", "team-a")
    monkeypatch.setenv("VMN_EXPERIMENT_ENDPOINT_URL", "http://minio:9000")
    params = {"backend": "local", "bucket": None, "prefix": "vmn-experiments"}

    merge_env_into_params(params)

    assert params["bucket"] == BUCKET
    assert params["prefix"] == "team-a"
    assert params["endpoint_url"] == "http://minio:9000"


def test_explicit_flags_beat_the_env(monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", BUCKET)
    params = {"bucket": "from-flag", "prefix": "custom"}

    merge_env_into_params(params)

    assert params == {"bucket": "from-flag", "prefix": "custom"}


def test_env_beats_conf_yml(monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", BUCKET)
    vcs = SimpleNamespace(experiment={"storage": {"bucket": "from-conf"}})
    params = {"backend": "local", "bucket": None}

    merge_conf_into_params(vcs, params)

    assert params["bucket"] == BUCKET


def _container(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": "trainer",
             "base_version": "1.2.0", "base_commit": "abc1234"}
        )
    )
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_BUCKET", BUCKET)


@pytest.fixture
def s3():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _bucket_runs():
    return [m["verstr"] for m in get_snapshot_storage(
        "s3", bucket=BUCKET, prefix="vmn-experiments", subdir="experiments"
    ).list_snapshots("trainer")]


def test_start_run_in_a_pod_records_straight_to_the_bucket(tmp_path, monkeypatch, s3):
    _container(tmp_path, monkeypatch)

    with start_run(note="pod") as run:
        run.log_metric("loss", 0.25)

    assert _bucket_runs() == [run.id]
    log = get_snapshot_storage(
        "s3", bucket=BUCKET, prefix="vmn-experiments", subdir="experiments"
    ).load_merged_log("trainer", run.id)
    assert any(e.get("values", {}).get("loss") == 0.25 for e in log)


def test_start_run_with_a_scratch_dir_also_syncs_to_the_bucket(tmp_path, monkeypatch, s3):
    _container(tmp_path, monkeypatch)
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "scratch"))

    with start_run() as run:
        run.log_metric("loss", 0.5)

    assert _bucket_runs() == [run.id]
    assert (tmp_path / "scratch" / ".vmn" / "trainer" / "experiments").is_dir()


def test_git_less_cli_create_records_to_the_env_bucket(tmp_path, monkeypatch, s3):
    from version_stamp.cli.entry import vmn_run

    _container(tmp_path, monkeypatch)

    err, _ = vmn_run(["exp", "create", "trainer", "--note", "cli pod"])

    assert err == 0
    assert len(_bucket_runs()) == 1
