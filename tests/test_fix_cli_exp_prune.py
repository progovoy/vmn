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


def _prune_v(app_layout, capfd, verstr, *extra):
    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", version=verstr, extra_args=list(extra))
    return err, capfd.readouterr().out


def _tag(app_layout, verstr, *pairs):
    assert _exp(app_layout.app_name, action="tag", extra_args=[verstr, *pairs]) == 0


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


def test_prune_protects_tagged_runs(app_layout, capfd):
    _bootstrap(app_layout)
    prod = _create(app_layout)
    other = _create(app_layout)
    _tag(app_layout, prod, "stage=prod")

    err, out = _prune(app_layout, capfd, "--protect-tag", "stage", keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == [prod]
    assert other in out
    assert "protected" in out.lower() and prod in out


def test_prune_without_protect_tag_flag_still_prunes_tagged_runs(app_layout, capfd):
    _bootstrap(app_layout)
    prod = _create(app_layout)
    _tag(app_layout, prod, "stage=prod")

    err, out = _prune(app_layout, capfd, keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == []


def test_prune_force_deletes_tag_protected_runs(app_layout, capfd):
    _bootstrap(app_layout)
    prod = _create(app_layout)
    _tag(app_layout, prod, "stage=prod")

    err, out = _prune(app_layout, capfd, "--protect-tag", "stage", "--force", keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == []


def test_prune_protects_ancestor_of_tag_protected_run(app_layout, capfd):
    _bootstrap(app_layout)
    outer = _create(app_layout)
    unrelated = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)
    _tag(app_layout, inner, "stage=prod")

    err, out = _prune(app_layout, capfd, "--protect-tag", "stage", keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == [outer, inner]
    assert unrelated in out


def test_prune_v_deletes_exactly_one_run(app_layout, capfd):
    _bootstrap(app_layout)
    a = _create(app_layout)
    b = _create(app_layout)
    c = _create(app_layout)

    err, out = _prune_v(app_layout, capfd, b)
    assert err == 0, out
    assert _verstrs(app_layout) == [a, c]
    assert b in out


def test_prune_v_dry_run_previews_only(app_layout, capfd):
    _bootstrap(app_layout)
    a = _create(app_layout)

    err, out = _prune_v(app_layout, capfd, a, "--dry-run")
    assert err == 0, out
    assert _verstrs(app_layout) == [a]
    assert "Would delete" in out and a in out


def test_prune_v_skips_running_run_without_force(app_layout, capfd):
    _bootstrap(app_layout)
    live = _create(app_layout)
    _mark_running(app_layout, live)

    err, out = _prune_v(app_layout, capfd, live)
    assert err == 0, out
    assert _verstrs(app_layout) == [live]
    assert "running" in out


def test_prune_v_force_deletes_running_run(app_layout, capfd):
    _bootstrap(app_layout)
    live = _create(app_layout)
    _mark_running(app_layout, live)

    err, out = _prune_v(app_layout, capfd, live, "--force")
    assert err == 0, out
    assert _verstrs(app_layout) == []


def test_prune_v_refuses_tag_protected_run_without_force(app_layout, capfd):
    _bootstrap(app_layout)
    prod = _create(app_layout)
    _tag(app_layout, prod, "stage=prod")

    err, out = _prune_v(app_layout, capfd, prod, "--protect-tag", "stage")
    assert err == 0, out
    assert _verstrs(app_layout) == [prod]
    assert "protected" in out.lower()


def test_prune_v_force_overrides_tag_protection(app_layout, capfd):
    _bootstrap(app_layout)
    prod = _create(app_layout)
    _tag(app_layout, prod, "stage=prod")

    err, out = _prune_v(app_layout, capfd, prod, "--protect-tag", "stage", "--force")
    assert err == 0, out
    assert _verstrs(app_layout) == []


def test_prune_v_keeps_ancestor_when_it_has_a_kept_descendant(app_layout, capfd):
    _bootstrap(app_layout)
    outer = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)

    err, out = _prune_v(app_layout, capfd, outer)
    assert err == 0, out
    assert _verstrs(app_layout) == [outer, inner]


def test_prune_v_rejects_combination_with_keep(app_layout, capfd):
    _bootstrap(app_layout)
    a = _create(app_layout)

    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", version=a, keep=0)
    assert err == 1


def test_prune_v_unknown_ref_errors(app_layout, capfd):
    _bootstrap(app_layout)
    _create(app_layout)

    capfd.readouterr()
    err = _exp(
        app_layout.app_name,
        action="prune",
        version="0.0.1-dev.deadbeef.cafebabe",
    )
    assert err == 1


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
