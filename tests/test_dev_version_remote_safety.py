"""Safety snapshots go to the app's experiment store (conf
``experiment.storage``, ``snapshots`` subdir), and ``vmn goto`` finds them
there — also from a checkout that never had the local copy."""
import os
import re
import shutil
import subprocess

import boto3
import pytest
from moto import mock_aws

from helpers import _experiment, _goto, _init_app, _run_vmn_init, _stamp_app, extract_dev_verstr

BUCKET = "safety-bkt"


@pytest.fixture
def s3(monkeypatch):
    for key in ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_DIR"):
        monkeypatch.delenv(key, raising=False)
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _write(app_layout, name, content):
    path = os.path.join(app_layout.repo_path, name)
    with open(path, "w") as f:
        f.write(content)
    return path


def _read(path):
    with open(path) as f:
        return f.read()


def test_goto_restores_a_safety_snapshot_from_the_remote_store(app_layout, capfd, s3):
    app = app_layout.app_name
    _run_vmn_init()
    _, _, params = _init_app(app)
    app_layout.write_conf(
        params["app_conf_path"],
        template="[{major}][.{minor}][.{patch}]",
        experiment={"storage": {"uri": f"s3://{BUCKET}/team"}},
    )
    _stamp_app(app, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "safety.txt", "committed")
    path = _write(app_layout, "safety.txt", "state A")
    capfd.readouterr()
    assert _experiment(app) == 0
    v_a = extract_dev_verstr(capfd.readouterr().out)

    _write(app_layout, "safety.txt", "state B unsaved")
    assert _goto(app, version=v_a) == 0
    out = capfd.readouterr()
    saved = re.search(r"Current work saved as (\S+)", out.out + out.err).group(1)
    assert _read(path) == "state A"

    # Another checkout: no local copy of the safety snapshot.
    shutil.rmtree(os.path.join(app_layout.repo_path, ".vmn", app, "snapshots"))
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)

    assert _goto(app, version=saved) == 0
    assert _read(path) == "state B unsaved"
