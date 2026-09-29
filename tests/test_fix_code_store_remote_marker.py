"""A code object the local cache holds but its remote lacks is uploaded before
a run pointing at it is created there.

``stored_code`` reads the marker local-first, so a code object stored only
locally (a create whose remote leg failed, a run recorded without a remote)
used to be skipped: the remote run then pointed at a missing code object and
every other host read it as ``code_missing``.
"""
import os

import boto3
import pytest
from helpers import _bootstrap, _storage

from vmn_exp.sdk import start_run
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.s3 import S3SnapshotStorage

BUCKET = "vmn-code-marker"
URI = f"s3://{BUCKET}/exp"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (
        ("AWS_ACCESS_KEY_ID", "x"),
        ("AWS_SECRET_ACCESS_KEY", "x"),
        ("AWS_DEFAULT_REGION", "us-east-1"),
    ):
        monkeypatch.setenv(key, value)
    from moto import mock_aws

    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _dirty(app_layout):
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "committed")
    for name, content in (("tracked.txt", "dirty"), ("untracked.txt", "new file")):
        with open(os.path.join(app_layout.repo_path, name), "w") as f:
            f.write(content)


def _online(app_layout):
    return open_storage(URI, app_layout.repo_path, subdir="experiments")


def _run(app_layout, storage):
    with start_run(app_layout.app_name, storage=storage) as run:
        return run.id


def _remote_code_is_complete(app_layout, verstr):
    reader = open_storage(URI, None, subdir="experiments")
    meta, patches = reader.load(app_layout.app_name, verstr)
    return "code_missing" not in meta and bool(patches.get("untracked_files"))


def _code_puts(calls):
    return [p["Key"] for op, p in calls if op == "PutObject" and "/vmn-code-" in p["Key"]]


def test_code_stored_locally_only_is_uploaded_on_next_online_create(app_layout):
    _bootstrap(app_layout)
    _dirty(app_layout)
    _run(app_layout, _storage(app_layout))  # no remote configured yet

    online_run = _run(app_layout, _online(app_layout))

    assert _remote_code_is_complete(app_layout, online_run)


def test_retry_after_remote_code_save_failure_uploads_code(app_layout, monkeypatch):
    _bootstrap(app_layout)
    _dirty(app_layout)
    real_save = S3SnapshotStorage.save
    failures = []

    def flaky_save(self, app_name, verstr, metadata, patches):
        if app_name.startswith("vmn-code/") and not failures:
            failures.append(verstr)
            raise RuntimeError("transient S3 error")
        return real_save(self, app_name, verstr, metadata, patches)

    monkeypatch.setattr(S3SnapshotStorage, "save", flaky_save)
    with pytest.raises(RuntimeError):
        _run(app_layout, _online(app_layout))
    assert failures

    retried = _run(app_layout, _online(app_layout))

    assert _remote_code_is_complete(app_layout, retried)


def test_remote_marker_present_makes_no_upload(app_layout):
    from s3_helpers import record_calls

    _bootstrap(app_layout)
    _dirty(app_layout)
    _run(app_layout, _online(app_layout))

    storage = _online(app_layout)  # a fresh process: nothing memoized
    calls = record_calls(storage._remote._s3)
    second = _run(app_layout, storage)

    assert _code_puts(calls) == []
    assert _remote_code_is_complete(app_layout, second)
