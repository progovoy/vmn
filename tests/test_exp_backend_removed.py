"""``vmn exp --backend`` is gone: the bucket (flag > ``VMN_EXPERIMENT_BUCKET`` >
conf.yml) alone selects S3.
"""
import os
import subprocess

import boto3
import pytest
import yaml
from moto import mock_aws

from helpers import _PY, _SRC_PATH
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.snapshot import get_snapshot_storage

BUCKET = "ml-exps"
APP = "trainer"
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


@pytest.fixture
def s3():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _container(tmp_path, monkeypatch):
    """A git-less image: snapshot metadata and a scratch experiment dir."""
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": APP,
             "base_version": "1.2.0", "base_commit": "abc1234"}
        )
    )
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    return image


def _local_runs(root):
    local = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")
    return local.list_snapshots(APP)


def _bucket_runs():
    return get_snapshot_storage(
        "s3", bucket=BUCKET, prefix="vmn-experiments", subdir="experiments"
    ).list_snapshots(APP)


def test_backend_flag_is_rejected(tmp_path):
    result = _run_cli(tmp_path, "exp", "list", APP, "--backend", "s3")

    assert result.returncode == 2
    assert "--backend" in result.stderr


def test_backend_flag_is_absent_from_exp_help(tmp_path):
    result = _run_cli(tmp_path, "exp", "--help")

    assert result.returncode == 0, result.stderr
    assert "--bucket" in result.stdout
    assert "--backend" not in result.stdout


def test_git_less_run_without_a_bucket_records_to_the_local_dir(tmp_path, monkeypatch):
    _container(tmp_path, monkeypatch)
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(scratch))

    err, _ = vmn_exp_run(["exp", "create", APP])

    assert err == 0
    assert len(_local_runs(scratch)) == 1


def test_bucket_flag_alone_selects_s3(tmp_path, monkeypatch, s3):
    _container(tmp_path, monkeypatch)

    err, _ = vmn_exp_run(["exp", "create", APP, "--bucket", BUCKET])

    assert err == 0
    assert len(_bucket_runs()) == 1


def _run_cli(tmp_path, *argv):
    env = dict(os.environ, PYTHONPATH=_SRC_PATH, VMN_WORKING_DIR=str(tmp_path))
    return subprocess.run(
        [_PY, "-m", "vmn_exp.cli", *argv],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
