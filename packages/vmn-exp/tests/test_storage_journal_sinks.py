"""Journal sinks: where entries land, the reader's ``list_fn`` over each
backend's listing, ``open_storage`` wrapping, and pruning old partitions."""
import os
import time

import boto3
import pytest
from moto import mock_aws

from object_store_fakes import (
    FakeContainerClient,
    FakeGCSClient,
    MatchConditions,
)
from vmn_exp.core.journal_keys import JournalKey, encode_key, partition_of
from vmn_exp.storage.journal import JournaledStorage, prune_journal
from vmn_exp.storage.journal_sinks import journal_list_fn, sink_for
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage

APP = "trainer"
V1 = "1.2.0-dev.abc1234.0000001"
NOW_MS = 1_790_000_000_000
DAY_MS = 86_400_000


def _key(ms, name="r"):
    return encode_key(JournalKey(ms, "runs", APP, "w", 0, name))


@pytest.fixture(params=["local", "s3", "gs", "az"])
def backend(request, monkeypatch, tmp_path):
    scheme = request.param
    if scheme == "local":
        yield LocalSnapshotStorage(str(tmp_path), "runs")
        return
    if scheme == "s3":
        for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                         AWS_DEFAULT_REGION="us-east-1").items():
            monkeypatch.setenv(k, v)
        with mock_aws():
            boto3.client("s3").create_bucket(Bucket="bkt")
            from vmn_exp.storage.s3 import S3SnapshotStorage

            yield S3SnapshotStorage("bkt", prefix="root/runs")
        return
    if scheme == "gs":
        from vmn_exp.storage.gcs import GCSSnapshotStorage

        yield GCSSnapshotStorage("bkt", prefix="root/runs", client=FakeGCSClient())
        return
    from vmn_exp.storage.azure import AzureSnapshotStorage

    yield AzureSnapshotStorage(
        "bkt", prefix="root/runs", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


def test_list_fn_returns_keys_after_start_after_in_order(backend):
    sink = sink_for(backend)
    keys = [_key(NOW_MS + i, f"r{i}") for i in range(5)]
    for key in reversed(keys):
        sink.put(key)
    list_fn = journal_list_fn(backend)
    prefix = f"journal/{partition_of(NOW_MS)}/"
    assert list(list_fn(prefix, None)) == keys
    assert list(list_fn(prefix, keys[1])) == keys[2:]


def test_entries_share_one_root_across_areas(backend):
    sink_for(backend.in_area("code")).put(_key(NOW_MS))
    prefix = f"journal/{partition_of(NOW_MS)}/"
    assert list(journal_list_fn(backend)(prefix, None)) == [_key(NOW_MS)]


def test_prune_drops_partitions_older_than_two_days(backend):
    sink = sink_for(backend)
    old, recent = _key(NOW_MS - 3 * DAY_MS), _key(NOW_MS - DAY_MS)
    sink.put(old)
    sink.put(recent)
    prune_journal(backend, now=NOW_MS / 1000)
    list_fn = journal_list_fn(backend)
    assert list(list_fn(old.rpartition("/")[0] + "/", None)) == []
    assert list(list_fn(recent.rpartition("/")[0] + "/", None)) == [recent]


def test_local_entries_live_under_the_root_journal_dir(tmp_path):
    sink_for(LocalSnapshotStorage(str(tmp_path), "runs")).put(_key(NOW_MS))
    assert os.path.isfile(tmp_path / "journal" / _key(NOW_MS)[len("journal/"):])


def test_open_storage_journals_the_repo_local_root(tmp_path):
    storage = open_storage(None, str(tmp_path), area="runs")
    storage.create_exclusive(APP, V1, {"verstr": V1}, {})
    prefix = f"journal/{partition_of(int(time.time() * 1000))}/"
    listed = list(journal_list_fn(storage)(prefix, None))
    assert len(listed) == 1 and V1 in listed[0]


def test_open_storage_journals_a_file_store(tmp_path):
    storage = open_storage(f"file://{tmp_path}", None, area="runs")
    storage.create_exclusive(APP, V1, {"verstr": V1}, {})
    assert os.listdir(tmp_path / "journal")


def test_open_storage_journals_the_remote_not_the_cache(tmp_path, monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="bkt")
        storage = open_storage("s3://bkt/root", str(tmp_path), area="runs")
        assert isinstance(storage._remote, JournaledStorage)
        assert not isinstance(storage._local, JournaledStorage)
        storage.create_exclusive(APP, V1, {"verstr": V1}, {})
        listed = boto3.client("s3").list_objects_v2(Bucket="bkt", Prefix="root/journal/")
        assert listed["KeyCount"] == 1
        assert not (tmp_path / "journal").exists()


def test_cached_log_sync_journals_the_segment(tmp_path, monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="bkt")
        storage = open_storage("s3://bkt/root", str(tmp_path), area="runs")
        storage.create_exclusive(APP, V1, {"verstr": V1}, {})
        storage.append_log_entries(APP, V1, "w", [{"type": "metric"}])
        storage.sync_log_to_remote(APP, V1, "w")
        listed = boto3.client("s3").list_objects_v2(Bucket="bkt", Prefix="root/journal/")
        assert listed["KeyCount"] == 2


def test_vmn_exp_prune_trims_old_journal_partitions(tmp_path):
    from types import SimpleNamespace

    from vmn_exp.cli.prune import experiment_prune

    storage = open_storage(None, str(tmp_path), area="runs")
    old = _key(int(time.time() * 1000) - 3 * DAY_MS)
    sink_for(LocalSnapshotStorage(str(tmp_path), "runs")).put(old)
    args = SimpleNamespace(keep=0, older_than=None, force=False)
    assert experiment_prune(None, {}, storage, args, APP) == 0
    assert not (tmp_path / old.rpartition("/")[0]).exists()
