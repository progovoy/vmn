"""The per-code-identity code store on S3, and prune keeping shared code."""
import os
import shutil
import subprocess

import boto3
import pytest
from exp_helpers import _bootstrap, _exp, _storage

import version_stamp.devversion.untracked as dv_untracked
from vmn_exp.core.code_store import code_storage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.sdk import start_run
from vmn_exp.storage.files import METADATA_FILE, PATCH_FILES
from vmn_exp.storage.open import open_storage

BUCKET = "vmn-code-store"
PATCH_NAMES = {filename for _, filename, _ in PATCH_FILES}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


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


@pytest.fixture
def tarballs(monkeypatch):
    calls = []
    real = dv_untracked._collect_untracked_tarball

    def spy(repo_path):
        calls.append(repo_path)
        return real(repo_path)

    monkeypatch.setattr(dv_untracked, "_collect_untracked_tarball", spy)
    return calls


def _keys(client):
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET)
    return [o["Key"] for page in pages for o in page.get("Contents", [])]


def _write(app_layout, name, content):
    with open(os.path.join(app_layout.repo_path, name), "w") as f:
        f.write(content)


def _read(app_layout, name):
    with open(os.path.join(app_layout.repo_path, name)) as f:
        return f.read()


def _dirty(app_layout, untracked="new file"):
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "committed")
    _write(app_layout, "tracked.txt", "dirty")
    _write(app_layout, "untracked.txt", untracked)


def _clean_tree(app_layout):
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)
    os.remove(os.path.join(app_layout.repo_path, "untracked.txt"))


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _code_objects(client, app_name):
    """``{code key: [file names]}`` in the bucket's code store for *app_name*."""
    found = {}
    marker = f"/code/{app_name.replace('/', '-')}/"
    for key in _keys(client):
        if marker in key:
            code_key, _, name = key.split(marker, 1)[1].partition("/")
            found.setdefault(code_key, []).append(name)
    return found


def _drop_local_copies(app_layout):
    store = local_store_root(app_layout.repo_path)
    shutil.rmtree(os.path.join(store, "runs", app_layout.app_name))
    shutil.rmtree(os.path.join(store, "code"))


def test_runs_synced_to_s3_share_one_remote_code_object(app_layout, s3, tarballs):
    _bootstrap(app_layout)
    _dirty(app_layout)
    first = _create(app_layout, "--bucket", BUCKET)
    second = _create(app_layout, "--bucket", BUCKET)

    assert len(tarballs) == 1
    objects = _code_objects(s3, app_layout.app_name)
    assert len(objects) == 1
    assert METADATA_FILE in next(iter(objects.values()))
    run_files = {k.rsplit("/", 1)[1] for k in _keys(s3) if f"/{first}/" in k or f"/{second}/" in k}
    assert not run_files & PATCH_NAMES

    _drop_local_copies(app_layout)
    _clean_tree(app_layout)
    assert _exp(
        app_layout.app_name, action="restore", version=second, extra_args=["--bucket", BUCKET]
    ) == 0
    assert _read(app_layout, "untracked.txt") == "new file"
    assert _read(app_layout, "tracked.txt") == "dirty"


def test_runs_straight_to_s3_without_a_local_dir(app_layout, s3, tarballs):
    _bootstrap(app_layout)
    _dirty(app_layout, untracked="remote only")
    storage = open_storage(f"s3://{BUCKET}/exp", None, area="runs", buffer_logs=True)

    ids = []
    for _ in range(2):
        with start_run(app_layout.app_name, storage=storage) as run:
            ids.append(run.id)

    assert len(tarballs) == 1
    assert len(_code_objects(s3, app_layout.app_name)) == 1
    reader = open_storage(f"s3://{BUCKET}/exp", None, area="runs")
    for verstr in ids:
        meta, patches = reader.load(app_layout.app_name, verstr)
        assert meta["code"]
        assert patches["untracked_files"] and patches["working_tree"]


def test_an_incomplete_s3_code_object_is_rewritten_and_flagged_meanwhile(
    app_layout, s3, tarballs
):
    _bootstrap(app_layout)
    _dirty(app_layout)
    storage = open_storage(f"s3://{BUCKET}/exp", None, area="runs")
    with start_run(app_layout.app_name, storage=storage) as run:
        pass
    marker = next(k for k in _keys(s3) if "/code/" in k and k.endswith(METADATA_FILE))
    s3.delete_object(Bucket=BUCKET, Key=marker)

    meta, patches = storage.load(app_layout.app_name, run.id)
    assert meta["code_missing"] is True
    assert not any(patches.values())

    with start_run(app_layout.app_name, storage=storage):
        pass
    assert len(tarballs) == 2
    meta, patches = storage.load(app_layout.app_name, run.id)
    assert "code_missing" not in meta
    assert patches["untracked_files"]


def _prune_v(app_layout, verstr, *extra):
    return _exp(app_layout.app_name, action="prune", version=verstr, extra_args=list(extra))


@pytest.mark.parametrize("remote", [False, True])
def test_prune_keeps_shared_code_until_its_last_run_goes(app_layout, s3, remote):
    extra = ["--bucket", BUCKET] if remote else []
    _bootstrap(app_layout)
    _dirty(app_layout)
    first, second = _create(app_layout, *extra), _create(app_layout, *extra)
    storage = _storage(app_layout)
    (key,) = code_storage(storage).list_verstrs(app_layout.app_name)

    assert _prune_v(app_layout, first, *extra) == 0
    assert code_storage(storage).list_verstrs(app_layout.app_name) == [key]
    _, patches = storage.load(app_layout.app_name, second)
    assert patches["untracked_files"]

    assert _prune_v(app_layout, second, *extra) == 0
    assert code_storage(storage).list_verstrs(app_layout.app_name) == []
    if remote:
        assert _code_objects(s3, app_layout.app_name) == {}


def test_prune_removes_an_incomplete_code_object_with_its_last_run(app_layout):
    _bootstrap(app_layout)
    _dirty(app_layout)
    verstr = _create(app_layout)
    storage = _storage(app_layout)
    (key,) = code_storage(storage).list_verstrs(app_layout.app_name)
    code_dir = code_storage(storage._local)._snapshot_dir(app_layout.app_name, key)
    os.remove(os.path.join(code_dir, METADATA_FILE))

    assert _prune_v(app_layout, verstr) == 0
    assert not os.path.exists(code_dir)


def test_prune_keeps_code_of_other_identities(app_layout):
    _bootstrap(app_layout)
    _dirty(app_layout, untracked="one")
    doomed = _create(app_layout)
    _write(app_layout, "untracked.txt", "two")
    kept = _create(app_layout)
    storage = _storage(app_layout)
    kept_code = storage.load_metadata(app_layout.app_name, kept)["code"]

    assert _prune_v(app_layout, doomed) == 0
    assert code_storage(storage).list_verstrs(app_layout.app_name) == [kept_code]
