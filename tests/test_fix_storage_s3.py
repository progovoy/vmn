"""Storage contract (S3 + multi-host side): atomic allocation across hosts,
volatile files never cached, per-writer log merge, incremental segment sync,
injective app keys, cheap exists, streaming artifacts."""

import datetime
import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from version_stamp.cli.snapshot import (
    S3SnapshotStorage,
    get_snapshot_storage,
)
from version_stamp.core.experiment_status import derive_status, load_run_state
from version_stamp.core.experiment_writer import allocate_run_verstr
from version_stamp.core.logging import init_stamp_logger

BUCKET = "vmn-bucket"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1"
    ).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    try:
        init_stamp_logger()
    except Exception:
        pass
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _host(tmp_path, name):
    return get_snapshot_storage(
        "local",
        vmn_root_path=str(tmp_path / name),
        bucket=BUCKET,
        prefix="exps",
        subdir="experiments",
    )


def _s3():
    return S3SnapshotStorage(BUCKET, prefix="exps")


def _meta(verstr, **kw):
    return dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, **kw)


def _record(host):
    return lambda verstr: (_meta(verstr, host=host), {})


def test_two_hosts_on_the_same_commit_get_distinct_verstrs(tmp_path):
    a, b = _host(tmp_path, "a"), _host(tmp_path, "b")
    va = allocate_run_verstr(a, "app", "0.0.1-dev.abc", make_record=_record("A"))
    vb = allocate_run_verstr(b, "app", "0.0.1-dev.abc", make_record=_record("B"))
    assert va != vb
    hosts = {m["verstr"]: m["host"] for m in _s3().list_snapshots("app")}
    assert hosts == {va: "A", vb: "B"}


def test_allocation_lists_names_only(tmp_path, monkeypatch):
    a = _host(tmp_path, "a")
    a.save("app", "c", _meta("c"), {})
    monkeypatch.setattr(
        type(a), "list_snapshots", lambda *x: (_ for _ in ()).throw(AssertionError)
    )
    assert allocate_run_verstr(a, "app", "c", make_record=_record("A")) == "c.r2"


def test_s3_create_exclusive_is_conditional():
    s3 = _s3()
    assert s3.create_exclusive("app", "v1", _meta("v1", n=1), {})
    assert not s3.create_exclusive("app", "v1", _meta("v1", n=2), {})
    assert s3.load("app", "v1")[0]["n"] == 1


def test_remote_run_state_is_never_cached_locally(tmp_path):
    a, b = _host(tmp_path, "a"), _host(tmp_path, "b")
    b.save("app", "v", _meta("v"), {})
    old = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    ).isoformat()
    b.save_file("app", "v", "run_state.yml", f"state: running\nheartbeat: '{old}'\n")
    assert derive_status(load_run_state(a, "app", "v")) == "stuck"
    b.save_file("app", "v", "run_state.yml", "state: finished\nexit_code: 0\n")
    assert derive_status(load_run_state(a, "app", "v")) == "succeeded"


def test_cached_merged_log_unions_local_and_remote_writers(tmp_path):
    a, b = _host(tmp_path, "a"), _host(tmp_path, "b")
    a.save("app", "v", _meta("v"), {})
    a.append_log_entry("app", "v", "hostA", {"timestamp": "t1", "type": "note"})
    a.sync_log_to_remote("app", "v", "hostA")
    b.load("app", "v")  # b caches the metadata locally
    b.append_log_entry("app", "v", "hostB", {"timestamp": "t2", "type": "note"})
    b.sync_log_to_remote("app", "v", "hostB")
    a.append_log_entry("app", "v", "hostA", {"timestamp": "t3", "type": "note"})
    writers = [e["_writer"] for e in a.load_merged_log("app", "v")]
    assert writers == ["hostA", "hostB", "hostA"]


def test_appending_to_another_hosts_record_pulls_it_in(tmp_path):
    a, b = _host(tmp_path, "a"), _host(tmp_path, "b")
    a.save("app", "v", _meta("v"), {})
    assert b.append_log_entry("app", "v", "hostB", {"timestamp": "t", "type": "note"})
    b.sync_log_to_remote("app", "v", "hostB")
    assert [e["_writer"] for e in a.load_merged_log("app", "v")] == ["hostB"]


def _remote_log_keys(verstr="v"):
    resp = boto3.client("s3").list_objects_v2(
        Bucket=BUCKET, Prefix=f"exps/app/{verstr}/log."
    )
    return {o["Key"].rsplit("/", 1)[1]: o["Size"] for o in resp.get("Contents", [])}


def test_sync_uploads_only_new_bytes_as_segments(tmp_path):
    a = _host(tmp_path, "a")
    a.save("app", "v", _meta("v"), {})
    for i in range(3):
        a.append_log_entry("app", "v", "w", {"timestamp": f"t{i}", "type": "note"})
        a.sync_log_to_remote("app", "v", "w")
    a.sync_log_to_remote("app", "v", "w")  # nothing new: no object
    keys = _remote_log_keys()
    assert sorted(keys) == ["log.w.jsonl", "log.w@000001.jsonl", "log.w@000002.jsonl"]
    local_size = os.path.getsize(
        os.path.join(a._local._snapshot_dir("app", "v"), "log.w.jsonl")
    )
    assert sum(keys.values()) == local_size
    assert [e["timestamp"] for e in _s3().load_merged_log("app", "v")] == [
        "t0",
        "t1",
        "t2",
    ]
    assert {e["_writer"] for e in _s3().load_merged_log("app", "v")} == {"w"}


def test_sync_after_restart_resumes_from_remote_sizes(tmp_path):
    a = _host(tmp_path, "a")
    a.save("app", "v", _meta("v"), {})
    a.append_log_entry("app", "v", "w", {"timestamp": "t0", "type": "note"})
    a.sync_log_to_remote("app", "v", "w")
    a2 = _host(tmp_path, "a")  # a new process: no in-memory offset
    a2.append_log_entry("app", "v", "w", {"timestamp": "t1", "type": "note"})
    a2.sync_log_to_remote("app", "v", "w")
    assert [e["timestamp"] for e in _s3().load_merged_log("app", "v")] == ["t0", "t1"]


def test_pure_s3_appends_do_not_rewrite_the_log():
    s3 = _s3()
    s3.save("app", "v", _meta("v"), {})
    with patch.object(s3, "load_file", side_effect=AssertionError("no RMW")):
        for i in range(3):
            s3.append_log_entry("app", "v", "w", {"timestamp": f"t{i}", "type": "n"})
    assert [e["timestamp"] for e in s3.load_merged_log("app", "v")] == [
        "t0",
        "t1",
        "t2",
    ]


def test_s3_app_keys_are_injective():
    s3 = _s3()
    s3.save("my_app", "v1", _meta("v1"), {})
    s3.save("my/app", "v2", _meta("v2"), {})
    assert [m["verstr"] for m in s3.list_snapshots("my_app")] == ["v1"]
    assert [m["verstr"] for m in s3.list_snapshots("my/app")] == ["v2"]
    assert s3.list_verstrs("my/app") == ["v2"]


def test_s3_reads_fall_back_to_the_legacy_underscore_prefix():
    body = b"verstr: old\ntimestamp: '2025-01-01T00:00:00Z'\n"
    boto3.client("s3").put_object(
        Bucket=BUCKET, Key="exps/root_svc/old/metadata.yml", Body=body
    )
    s3 = _s3()
    assert [m["verstr"] for m in s3.list_snapshots("root/svc")] == ["old"]
    assert s3.exists("root/svc", "old")
    assert s3.load("root/svc", "old")[0]["verstr"] == "old"


def test_list_apps_from_storage_decodes_app_names():
    from version_stamp.ui.readers.experiments import list_apps_from_storage

    s3 = _s3()
    s3.save("my_app", "v1", _meta("v1"), {})
    s3.save("root/svc", "v2", _meta("v2"), {})
    rows = {r["name"]: r["experiments"] for r in list_apps_from_storage(s3)}
    assert rows == {"my_app": 1, "root/svc": 1}


def test_s3_exists_is_a_head_request():
    s3 = _s3()
    s3.save("app", "v", _meta("v"), {"untracked_files": b"x" * 1000})
    calls = []
    s3._s3.meta.events.register(
        "before-call.s3",
        lambda event_name, **kw: calls.append(event_name.split(".")[-1]),
    )
    assert s3.exists("app", "v") and not s3.exists("app", "nope")
    assert calls == ["HeadObject", "HeadObject"]


def test_s3_list_snapshots_keeps_timestamp_order():
    s3 = _s3()
    for i in (3, 1, 2):
        s3.save("app", f"v{i}", _meta(f"v{i}", timestamp=f"2026-01-0{i}T00:00:00Z"), {})
    assert [m["verstr"] for m in s3.list_snapshots("app")] == ["v1", "v2", "v3"]


def test_s3_artifacts_stream_list_and_download(tmp_path):
    s3 = _s3()
    s3.save("app", "v", _meta("v"), {})
    src = tmp_path / "model.pt"
    src.write_bytes(b"w" * 2048)
    s3.save_artifact_file("app", "v", str(src))
    assert s3.list_artifacts("app", "v") == [{"name": "model.pt", "size": 2048}]
    path = s3.artifact_local_path("app", "v", "model.pt")
    assert open(path, "rb").read() == b"w" * 2048
    assert s3.artifact_local_path("app", "v", "../metadata.yml") is None
    assert s3.artifact_local_path("app", "v", "missing") is None


def test_s3_artifact_upload_uses_upload_file(tmp_path):
    s3 = _s3()
    s3.save("app", "v", _meta("v"), {})
    src = tmp_path / "ckpt.bin"
    src.write_bytes(b"c" * 10)
    # upload_file streams from the path (multipart above its threshold); the old
    # code read the whole file into one put_object body.
    with patch.object(s3._s3, "upload_file", wraps=s3._s3.upload_file) as up:
        s3.save_artifact_file("app", "v", str(src))
    up.assert_called_once()
    assert up.call_args[0][0] == str(src)


def test_core_list_artifacts_delegates_to_storage():
    from version_stamp.core.experiment_log import list_artifacts

    class _St:
        def list_artifacts(self, app, verstr):
            return [{"name": "a", "size": 1}]

    assert list_artifacts(_St(), "app", "v") == [{"name": "a", "size": 1}]


def test_cached_list_verstrs_and_files_union_hosts(tmp_path):
    a, b = _host(tmp_path, "a"), _host(tmp_path, "b")
    a.save("app", "va", _meta("va"), {})
    b.save("app", "vb", _meta("vb"), {})
    assert sorted(a.list_verstrs("app")) == ["va", "vb"]
    assert set(_s3().list_files("app")) == {"va", "vb"}
    assert set(a.list_files("app")) == {"va", "vb"}
