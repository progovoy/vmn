"""``vmn goto -v <dev-version>`` finds experiment runs the way ``vmn-exp
restore`` does: the local experiments dir, then the app's remote experiment
store, then snapshots — and refuses runs that carry no code."""
import os
import re
import shutil

import boto3
import pytest
from moto import mock_aws

from exp_helpers import _experiment, _goto, _init_app, _run_vmn_init, _stamp_app, extract_dev_verstr

BUCKET = "goto-exp-bkt"
# No key prefix: experiments land under ``vmn-experiments/`` and snapshots
# under ``vmn-snapshots/``, so the snapshots lookup alone cannot find a run.
STORE = f"s3://{BUCKET}"


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


def _recorded_run(app_layout, capfd):
    """An app on the S3 store with one experiment recording `state A`."""
    app = app_layout.app_name
    _run_vmn_init()
    _, _, params = _init_app(app)
    app_layout.write_conf(
        params["app_conf_path"],
        template="[{major}][.{minor}][.{patch}]",
        experiment={"storage": {"uri": STORE}},
    )
    _stamp_app(app, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "exp.txt", "committed")
    path = _write(app_layout, "exp.txt", "state A")
    capfd.readouterr()
    assert _experiment(app) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr
    return app, path, verstr


def _local_experiments(app_layout, app):
    return os.path.join(app_layout.repo_path, ".vmn", app, "experiments")


def _spy_remote_loads(monkeypatch):
    from vmn_exp.storage.s3 import S3SnapshotStorage

    calls = []
    original = S3SnapshotStorage.load

    def spy(self, app_name, verstr):
        calls.append(verstr)
        return original(self, app_name, verstr)

    monkeypatch.setattr(S3SnapshotStorage, "load", spy)
    return calls


def test_goto_restores_a_run_only_in_the_remote_store(app_layout, capfd, s3):
    app, path, verstr = _recorded_run(app_layout, capfd)
    shutil.rmtree(_local_experiments(app_layout, app))
    _write(app_layout, "exp.txt", "committed")

    assert _goto(app, version=verstr) == 0
    assert _read(path) == "state A"


def test_goto_on_a_no_code_run_refuses_cleanly(app_layout, capfd, s3):
    from vmn_exp.storage.local import LocalSnapshotStorage

    app, _, verstr = _recorded_run(app_layout, capfd)
    local = LocalSnapshotStorage(app_layout.repo_path, subdir="experiments")
    meta, patches = local.load(app, verstr)
    meta.pop("base_commit")
    meta["imported_from"] = {"tool": "mlflow", "run_id": "abc123"}
    local.save(app, verstr, meta, patches)
    capfd.readouterr()

    assert _goto(app, version=verstr) == 1
    out = capfd.readouterr()
    text = out.out + out.err
    assert "no code snapshot" in text
    assert "Traceback" not in text


def test_goto_on_a_local_run_never_reads_the_remote(app_layout, capfd, s3, monkeypatch):
    app, path, verstr = _recorded_run(app_layout, capfd)
    _write(app_layout, "exp.txt", "committed")
    calls = _spy_remote_loads(monkeypatch)

    assert _goto(app, version=verstr) == 0
    assert _read(path) == "state A"
    assert calls == []


def test_goto_not_found_names_the_places_searched(app_layout, capfd, s3):
    app, _, verstr = _recorded_run(app_layout, capfd)
    missing = re.sub(r"-dev\.[0-9a-f]{7}", "-dev.0000000", verstr, count=1)
    assert missing != verstr
    capfd.readouterr()

    assert _goto(app, version=missing) == 1
    out = capfd.readouterr()
    text = out.out + out.err
    assert missing in text
    assert "local experiments" in text
    assert STORE in text
    assert "snapshots" in text
