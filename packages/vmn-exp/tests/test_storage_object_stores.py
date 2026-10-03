"""The backend contract, run against every object store: S3 (moto), GCS and
Azure Blob (in-memory fakes of their SDK clients).

What matters most is ``create_exclusive``: exactly one of several racing
writers may claim a name, which GCS gets from ``if_generation_match=0`` and
Azure from ``overwrite=False`` (``If-None-Match: *``).
"""
import threading

import boto3
import pytest
from moto import mock_aws

from object_store_fakes import (
    FakeContainerClient,
    FakeGCSClient,
    MatchConditions,
    install_fake_azure,
    install_fake_gcs,
)

APP = "trainer"
V1 = "1.2.0-dev.abc1234.0000001"
V2 = "1.2.0-dev.abc1234.0000002"
V3 = "1.2.0-dev.abc1234.0000003"


def _meta(verstr, **extra):
    return dict({"verstr": verstr, "app": APP, "format_version": 1}, **extra)


@pytest.fixture(params=["s3", "gs", "az"])
def store(request, monkeypatch):
    scheme = request.param
    if scheme == "s3":
        for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                         AWS_DEFAULT_REGION="us-east-1").items():
            monkeypatch.setenv(k, v)
        with mock_aws():
            boto3.client("s3").create_bucket(Bucket="bkt")
            from vmn_exp.storage.s3 import S3SnapshotStorage

            yield S3SnapshotStorage("bkt", prefix="p")
        return
    if scheme == "gs":
        from vmn_exp.storage.gcs import GCSSnapshotStorage

        yield GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())
        return
    from vmn_exp.storage.azure import AzureSnapshotStorage

    yield AzureSnapshotStorage(
        "bkt", prefix="p", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


def test_create_exclusive_claims_a_name_once(store):
    assert store.create_exclusive(APP, V1, _meta(V1), {"working_tree": "d"})
    assert not store.create_exclusive(APP, V1, _meta(V1, other=1), {})
    assert store.exists(APP, V1)
    assert store.load_metadata(APP, V1) == _meta(V1)
    metadata, patches = store.load(APP, V1)
    assert metadata == _meta(V1) and patches.get("working_tree") == "d"


def test_racing_writers_get_exactly_one_claim(store):
    wins, barrier = [], threading.Barrier(8)

    def claim(i):
        barrier.wait()
        if store.create_exclusive(APP, V1, _meta(V1, writer=i), {}):
            wins.append(i)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert store.load_metadata(APP, V1)["writer"] == wins[0]


def test_listing_pages_through_every_record(store):
    for v in (V1, V2, V3):
        store.create_exclusive(APP, v, _meta(v), {})
    assert sorted(store.list_verstrs(APP)) == [V1, V2, V3]
    assert sorted(m["verstr"] for m in store.list_snapshots(APP)) == [V1, V2, V3]
    files = store.list_files(APP)
    assert set(files) == {V1, V2, V3}
    assert files[V1]["metadata.yml"][0] > 0


def test_a_claimed_but_unfinished_name_is_invisible(store):
    store._put(f"{store._key_prefix(APP, V1)}/.claim", b"", IfNoneMatch="*")
    assert store.list_snapshots(APP) == [] and not store.exists(APP, V1)
    assert not store.create_exclusive(APP, V1, _meta(V1), {})


def test_update_metadata_merges_under_a_precondition(store):
    store.create_exclusive(APP, V1, _meta(V1), {})
    assert store.update_metadata(APP, V1, {"note": "hi"})
    assert store.update_note(APP, V1, "again")
    assert store.load_metadata(APP, V1)["note"] == "again"
    assert not store.update_metadata(APP, V2, {"note": "x"})


def test_ranged_reads_return_only_new_bytes(store):
    store.create_exclusive(APP, V1, _meta(V1), {})
    store.save_file(APP, V1, "log/w.jsonl", b"0123456789")
    assert store.read_file_from(APP, V1, "log/w.jsonl", 4) == b"456789"
    assert store.read_file_from(APP, V1, "log/w.jsonl", 10) == b""
    assert store.read_file_from(APP, V1, "missing", 3) is None
    assert store.load_file(APP, V1, "missing") is None


def test_log_appends_and_segments_merge(store):
    store.create_exclusive(APP, V1, _meta(V1), {})
    store.append_log_entries(APP, V1, "w", [{"type": "metric", "n": 1}])
    store.append_log_entries(APP, V1, "w", [{"type": "metric", "n": 2}])
    store.put_log_segment(APP, V1, "x", 0, b'{"type": "metric", "n": 3}\n')
    assert sorted(e["n"] for e in store.load_merged_log(APP, V1)) == [1, 2, 3]


def test_delete_hides_then_removes_the_record(store):
    store.create_exclusive(APP, V1, _meta(V1), {"working_tree": "d"})
    store.delete(APP, V1)
    assert not store.exists(APP, V1)
    assert store.list_verstrs(APP) == []
    assert store.create_exclusive(APP, V1, _meta(V1), {})


def test_artifacts_round_trip(store, tmp_path):
    store.create_exclusive(APP, V1, _meta(V1), {})
    src = tmp_path / "w.bin"
    src.write_bytes(b"weights-bytes")
    store.save_artifact_file(APP, V1, str(src), name="artifacts/model/w.bin")

    assert store.list_artifacts(APP, V1) == [{"name": "artifacts/model/w.bin", "size": 13}]
    with open(store.artifact_local_path(APP, V1, "artifacts/model/w.bin"), "rb") as f:
        assert f.read() == b"weights-bytes"
    chunks, size = store.open_artifact(APP, V1, "artifacts/model/w.bin")
    assert size == 13 and b"".join(chunks) == b"weights-bytes"
    assert store.open_artifact(APP, V1, "nope") is None
    assert store.artifact_uri(APP, V1, "artifacts/model/w.bin").startswith(
        f"{store.scheme}://bkt/p/"
    )


def test_cache_identities_differ_per_scheme(store):
    assert store.cache_identity()[0] == store.scheme
    assert store.is_remote()


def test_alert_markers_round_trip_once_per_transition(store):
    from types import SimpleNamespace

    from vmn_exp.core.alerts.transitions import ALERTS_FILE, alert_transition

    store.create_exclusive(APP, V1, _meta(V1), {})
    sent = []
    alerter = SimpleNamespace(send=lambda alert: sent.append(alert) or True)
    state = {"state": "finished", "exit_code": 1, "finished_at": "2026-01-01T00:00:00Z"}

    assert alert_transition(store, APP, V1, state, "failed", alerter)
    assert not alert_transition(store, APP, V1, state, "failed", alerter)
    assert len(sent) == 1
    assert b"failed@" in store.load_file(APP, V1, ALERTS_FILE)


def test_gcs_factory_builds_from_the_uri(monkeypatch):
    from vmn_exp.storage.registry import open_store

    client = FakeGCSClient()
    install_fake_gcs(monkeypatch, client)
    store = open_store("gs://bkt/team", area="runs")
    assert (store.bucket, store.prefix, store.scheme) == ("bkt", "team/runs", "gs")
    assert store.create_exclusive(APP, V1, _meta(V1), {})
    assert any(k.startswith("team/runs/trainer/") for k in client.bucket("bkt").objects)


def test_azure_factory_uses_the_connection_string(monkeypatch):
    from vmn_exp.storage.registry import open_store

    install_fake_azure(monkeypatch)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    store = open_store("az://ctr", area="runs")
    assert (store.bucket, store.prefix, store.scheme) == ("ctr", "vmn/runs", "az")
    assert store.create_exclusive(APP, V1, _meta(V1), {})
    assert not store.create_exclusive(APP, V1, _meta(V1), {})


def test_azure_factory_without_credentials_explains(monkeypatch):
    from vmn_exp.storage.registry import open_store

    install_fake_azure(monkeypatch)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    with pytest.raises(ValueError) as err:
        open_store("az://ctr/p")
    assert "AZURE_STORAGE_CONNECTION_STRING" in str(err.value)
