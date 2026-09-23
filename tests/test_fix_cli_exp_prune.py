"""`vmn exp prune` safety: live runs, run trees, dry runs and local-only."""
import os

import boto3
import pytest
import yaml
from helpers import _bootstrap, _exp, _storage

from version_stamp.core.utils import now_iso

BUCKET = "vmn-prune-bucket"


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _verstrs(app_layout):
    return [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]


def _mark_running(app_layout, verstr):
    state = {
        "state": "running",
        "pid": 1,
        "host": "h",
        "started_at": now_iso(),
        "heartbeat": now_iso(),
        "heartbeat_interval_sec": 30,
        "exit_code": None,
    }
    _storage(app_layout).save_file(
        app_layout.app_name, verstr, "run_state.yml", yaml.dump(state)
    )


def _prune(app_layout, capfd, *extra, keep=None):
    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", keep=keep, extra_args=list(extra))
    return err, capfd.readouterr().out


def test_prune_skips_running_runs(app_layout, capfd):
    _bootstrap(app_layout)
    live = _create(app_layout)
    done = _create(app_layout)
    _mark_running(app_layout, live)

    err, out = _prune(app_layout, capfd, keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == [live]
    assert done in out and "running" in out


def test_prune_force_deletes_running_runs(app_layout, capfd):
    _bootstrap(app_layout)
    live = _create(app_layout)
    _mark_running(app_layout, live)

    err, out = _prune(app_layout, capfd, "--force", keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == []


def test_prune_keeps_ancestors_of_kept_runs(app_layout, capfd):
    _bootstrap(app_layout)
    outer = _create(app_layout)
    unrelated = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)

    err, out = _prune(app_layout, capfd, keep=1)
    assert err == 0, out
    assert _verstrs(app_layout) == [outer, inner]
    assert unrelated in out


def test_prune_dry_run_deletes_nothing(app_layout, capfd):
    _bootstrap(app_layout)
    runs = [_create(app_layout), _create(app_layout)]

    err, out = _prune(app_layout, capfd, "--dry-run", keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == runs
    assert "Would delete" in out
    for verstr in runs:
        assert verstr in out


def test_prune_prints_each_deleted_run(app_layout, capfd):
    _bootstrap(app_layout)
    runs = [_create(app_layout), _create(app_layout), _create(app_layout)]

    err, out = _prune(app_layout, capfd, keep=1)
    assert err == 0, out
    assert "Pruned 2" in out
    for verstr in runs[:2]:
        assert verstr in out


@pytest.fixture
def s3(monkeypatch):
    from moto import mock_aws

    for key, value in (
        ("AWS_ACCESS_KEY_ID", "x"),
        ("AWS_SECRET_ACCESS_KEY", "x"),
        ("AWS_DEFAULT_REGION", "us-east-1"),
    ):
        monkeypatch.setenv(key, value)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _remote_keys(client):
    resp = client.list_objects_v2(Bucket=BUCKET)
    return [o["Key"] for o in resp.get("Contents", [])]


def test_prune_local_only_keeps_remote_copies(app_layout, capfd, s3):
    _bootstrap(app_layout)
    verstr = _create(app_layout, "--bucket", BUCKET)
    assert any(verstr.replace("+", "_plus_") in k for k in _remote_keys(s3))

    err, out = _prune(app_layout, capfd, "--bucket", BUCKET, "--local-only", keep=0)
    assert err == 0, out
    local_dir = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    assert not os.path.exists(local_dir)
    assert any(verstr.replace("+", "_plus_") in k for k in _remote_keys(s3))


def test_prune_default_deletes_remote_copies(app_layout, capfd, s3):
    _bootstrap(app_layout)
    verstr = _create(app_layout, "--bucket", BUCKET)

    err, out = _prune(app_layout, capfd, "--bucket", BUCKET, keep=0)
    assert err == 0, out
    assert not any(verstr.replace("+", "_plus_") in k for k in _remote_keys(s3))
