"""``vmn-exp similar-backfill`` on remote stores: through a checkout's
local-first cache (whose local copy of a writer's log may lag the remote's)
and git-free in a container (``VMN_SNAPSHOT_METADATA``) straight on a bucket."""
import boto3
import pytest
import yaml
from backfill_helpers import (
    CODE,
    CREATOR,
    FILES,
    as_backfiller,
    dirty_run,
    features_entries,
    host_logs,
    seed_code,
)
from exp_helpers import _bootstrap, _exp, _storage
from moto import mock_aws
from s3_helpers import BUCKET, PREFIX, cached_host, mocked_bucket, s3_storage
from vmn_exp.storage import buffered
from vmn_exp.storage.uri import s3_uri

V1 = CODE


def _note(text, second):
    return {"timestamp": f"2026-01-01T00:00:{second:02d}Z", "type": "note", "text": text}


@pytest.fixture
def bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


def test_a_cached_backfill_keeps_the_remote_entries_of_its_writer(
        app_layout, bucket, tmp_path, capfd, monkeypatch):
    _bootstrap(app_layout)
    app = app_layout.app_name
    other_clone = cached_host(tmp_path, "other-clone")
    seed_code(other_clone, app)
    dirty_run(other_clone, app, V1, log=[_note("n1", 2), _note("n2", 3)])
    other_clone.sync_log_to_remote(app, V1, CREATOR)
    as_backfiller(monkeypatch, CREATOR)  # this host writes under the same writer id
    capfd.readouterr()

    code = _exp(app, action="similar-backfill",
                extra_args=["--store", s3_uri(BUCKET, PREFIX)])

    assert code == 0, capfd.readouterr()
    remote_log = host_logs(s3_storage(), app, V1)[CREATOR]
    assert [e["type"] for e in remote_log] == ["create", "note", "note", "features"]
    assert sorted(remote_log[-1]["changed"]["files"]) == FILES
    local_log = host_logs(_storage(app_layout), app, V1)[CREATOR]
    assert [e["type"] for e in local_log] == ["features"]  # this clone's own stream


# -- git-free, on an S3 store ---------------------------------------------------

GIT_FREE_BUCKET = "backfill-bucket"
APP = "trainer"


@pytest.fixture
def container(tmp_path, monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump(
        {"verstr": CODE, "app_name": APP, "base_version": "0.0.2",
         "base_commit": "abc1234"}
    ))
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    as_backfiller(monkeypatch)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=GIT_FREE_BUCKET)
        yield
        buffered.close_all()


def test_backfill_works_git_free_on_s3(container, capfd):
    from vmn_exp.cli.main import vmn_exp_run
    from vmn_exp.storage.s3 import S3SnapshotStorage

    remote = S3SnapshotStorage(GIT_FREE_BUCKET, prefix="cli/runs")
    seed_code(remote, APP)
    dirty_run(remote, APP, V1)
    capfd.readouterr()

    store = ["--store", f"s3://{GIT_FREE_BUCKET}/cli"]
    assert vmn_exp_run(["exp", "similar-backfill", APP, *store])[0] == 0

    assert capfd.readouterr().out.splitlines()[-1] == \
        "backfilled 1, partial 0, skipped 0, failed 0"
    [entry] = features_entries(remote, APP, V1)
    assert sorted(entry["changed"]["files"]) == FILES
    assert entry["author"]["writer"] == CREATOR
