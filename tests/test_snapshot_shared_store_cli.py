"""`vmn snapshot --store` on a shared directory and on S3 (moto), without vmn-exp."""
import os
import subprocess

import pytest

from helpers import _bootstrap, _snapshot, extract_dev_verstr

from version_stamp.cli import plugins
from version_stamp.snapshot import opener as snapshot_opener


@pytest.fixture(autouse=True)
def without_vmn_exp(monkeypatch):
    monkeypatch.setattr(plugins, "_plugin_entry_points", lambda: [])
    monkeypatch.setattr(snapshot_opener, "_snapshot_store_opener", None)


def _dirty(app_layout, content):
    path = os.path.join(app_layout.repo_path, "work.txt")
    if not os.path.exists(path):
        app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "initial")
    with open(path, "w") as f:
        f.write(content)


def _run(app_layout, capfd, **kwargs):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, **kwargs)
    captured = capfd.readouterr()
    return ret, captured.out + captured.err


def _create(app_layout, capfd, store):
    ret, out = _run(app_layout, capfd, store=store)
    assert ret == 0, out
    return extract_dev_verstr(out)


def _local_snapshots(app_layout):
    return os.path.join(app_layout.repo_path, ".vmn", "store", "snapshots")


def test_directory_store_create_list_restore(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    _dirty(app_layout, "shared work")
    shared = tmp_path / "shared"
    uri = f"file://{shared}"
    verstr = _create(app_layout, capfd, uri)

    assert os.path.isfile(shared / "store.yml")
    assert os.listdir(shared / "snapshots" / app_layout.app_name)
    assert not os.path.isdir(_local_snapshots(app_layout))
    ret, out = _run(app_layout, capfd, action="list", store=uri)
    assert ret == 0 and verstr in out

    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)
    ret, out = _run(app_layout, capfd, action="restore", version=verstr, store=uri)
    assert ret == 0, out
    with open(os.path.join(app_layout.repo_path, "work.txt")) as f:
        assert f.read() == "shared work"


def test_listing_an_empty_directory_store_is_an_error(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    empty = tmp_path / "empty"
    empty.mkdir()
    ret, out = _run(app_layout, capfd, action="list", store=str(empty))
    assert ret == 1 and f"no vmn store at {empty}" in out


def _without_aws_credentials(monkeypatch, tmp_path):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
              "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
              "AWS_WEB_IDENTITY_TOKEN_FILE", "VMN_STORE_ENDPOINT_URL"):
        monkeypatch.delenv(k, raising=False)
    for k in ("AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE"):
        monkeypatch.setenv(k, str(tmp_path / "none"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def test_s3_store_without_credentials_fails_with_a_message(app_layout, capfd, monkeypatch,
                                                           tmp_path):
    pytest.importorskip("boto3")
    _without_aws_credentials(monkeypatch, tmp_path)
    _bootstrap(app_layout)
    ret, out = _run(app_layout, capfd, action="list", store="s3://no-creds-bucket/p")
    assert ret == 1
    assert ("s3://no-creds-bucket/p: cannot reach the store: "
            "NoCredentialsError: Unable to locate credentials") in out
    assert "Traceback" not in out


def test_s3_store_create_and_list(app_layout, capfd, monkeypatch):
    pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    from version_stamp.store.s3_client import boto3_client

    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    _bootstrap(app_layout)
    _dirty(app_layout, "s3 work")
    with moto.mock_aws():
        client = boto3_client(None)
        client.create_bucket(Bucket="team-bucket")
        verstr = _create(app_layout, capfd, "s3://team-bucket/team")
        ret, out = _run(app_layout, capfd, action="list", store="s3://team-bucket/team")
        keys = [o["Key"] for o in client.list_objects_v2(Bucket="team-bucket")["Contents"]]

    assert ret == 0 and verstr in out
    assert "team/store.yml" in keys
    assert any(k.startswith(f"team/snapshots/{app_layout.app_name}/") for k in keys)
    assert any(k.startswith(f"team/code/{app_layout.app_name}/") for k in keys)
    assert not os.path.isdir(_local_snapshots(app_layout))
