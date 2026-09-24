"""Direct-to-S3 experiments (a bucket, no local dir) buffer the log locally and
ship new lines as segments: an append never reads and rewrites the log."""
import functools

import pytest
import yaml
from s3_helpers import entry, meta, mocked_bucket, raw_keys, record_calls, s3_storage

from version_stamp.cli import snapshot_storage_buffered
from version_stamp.cli.experiment import _get_experiment_storage
from version_stamp.core.experiment_logfiles import compacted_log_name
from version_stamp.core.experiment_writer import append_entries_to_log
from version_stamp.exp import log_buffer
from version_stamp.exp.log_buffer import LogBuffer

V = "v"
PARAMS = {"bucket": "vmn-bucket", "prefix": "exps"}


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    with mocked_bucket(monkeypatch):
        yield
        # Ship what each test's pods still buffer while the bucket is mocked,
        # never at interpreter exit against a real endpoint.
        snapshot_storage_buffered.close_all()


def _pod():
    storage = _get_experiment_storage(None, dict(PARAMS))
    storage.create_exclusive("app", V, meta(V), {"working_tree": "diff"})
    return storage


def _values():
    return [e["values"]["i"] for e in s3_storage().load_merged_log("app", V)]


def _log_keys():
    return [k.rsplit("/", 1)[1] for k in raw_keys() if "/log." in k]


def test_appends_never_read_the_remote_log():
    pod = _pod()
    calls = record_calls(pod._remote._s3)
    for i in range(5):
        pod.append_log_entry("app", V, "w", entry(i))
    reads = [p["Key"] for op, p in calls if op == "GetObject" and "/log." in p["Key"]]
    assert reads == []


def test_the_first_append_reaches_the_bucket_at_once():
    pod = _pod()
    pod.append_log_entry("app", V, "w", entry(0))
    assert _values() == [0]


def test_buffered_lines_ship_as_segments_on_sync():
    pod = _pod()
    for i in range(3):
        pod.append_log_entry("app", V, "w", entry(i))
    pod.sync_log_to_remote("app", V, "w")
    assert _values() == [0, 1, 2]
    assert _log_keys() == ["log.w.jsonl", "log.w@000001.jsonl"]


def test_close_flushes_what_is_still_buffered():
    pod = _pod()
    for i in range(3):
        pod.append_log_entry("app", V, "w", entry(i))
    pod.close()
    assert _values() == [0, 1, 2]


def test_a_finished_run_ends_as_one_log_object():
    pod = _pod()
    for i in range(3):
        pod.append_log_entry("app", V, "w", entry(i))
        pod.sync_log_to_remote("app", V, "w")
    pod.save_file("app", V, "run_state.yml", yaml.dump({"state": "finished"}))
    pod.sync_log_to_remote("app", V, "w")
    assert _log_keys() == [compacted_log_name("w", 2)]


def test_the_record_body_is_not_kept_in_the_buffer():
    pod = _pod()
    assert pod.load("app", V)[1] == {"working_tree": "diff"}
    assert pod._local.load("app", V)[1] == {}


def test_appending_to_another_pods_run_needs_no_patch_download():
    _pod()
    other = _get_experiment_storage(None, dict(PARAMS))
    calls = record_calls(other._remote._s3)
    assert other.append_log_entry("app", V, "w2", entry(7))
    fetched = {p["Key"].rsplit("/", 1)[1] for op, p in calls if op == "GetObject"}
    assert "working_tree.patch" not in fetched
    assert 7 in _values()


def test_artifacts_go_straight_to_the_bucket(tmp_path):
    pod = _pod()
    src = tmp_path / "model.pt"
    src.write_bytes(b"w" * 64)
    assert pod.save_artifact_file("app", V, str(src))
    assert pod._local.list_artifact_files("app", V) is None
    assert s3_storage().list_artifacts("app", V) == [{"name": "model.pt", "size": 64}]


def test_reads_do_not_create_a_buffer_dir():
    import os

    storage = _get_experiment_storage(None, dict(PARAMS))
    storage.list_snapshots("app")
    assert not os.path.exists(storage._local.vmn_root_path)


def test_a_storage_with_nothing_pending_is_not_kept_alive():
    import gc
    import weakref

    pod = _pod()
    pod.append_log_entry("app", V, "w", entry(0))  # the first append ships at once
    ref = weakref.ref(pod)
    del pod
    gc.collect()
    assert ref() is None


def test_a_failed_ship_does_not_duplicate_log_lines(monkeypatch):
    """The store durably appends locally, then ships. A shipping failure (a
    network blip) must not be treated as a failed write: the SDK's LogBuffer
    retries a failed write by resubmitting the whole batch, and resubmitting
    entries that were already durably written would write them twice."""
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    pod = _pod()
    real_ship = pod._ship
    state = {"failed": False}

    def flaky_ship(app_name, verstr, writer_id, seq, chunk):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("network blip")
        return real_ship(app_name, verstr, writer_id, seq, chunk)

    monkeypatch.setattr(pod, "_ship", flaky_ship)

    buf = LogBuffer(functools.partial(append_entries_to_log, pod, "app", V))
    for i in range(3):
        buf.append(entry(i))

    buf.flush()  # the local write succeeds; shipping fails but must not raise
    local_steps = [e["values"]["i"] for e in pod._local.load_merged_log("app", V)]

    pod.close()  # the storage's own retry mechanism ships what is still buffered

    assert local_steps == [0, 1, 2]
    assert _values() == [0, 1, 2]


def test_pending_lines_are_shipped_at_exit_even_if_the_storage_was_dropped():
    pod = _pod()
    for i in range(3):
        pod.append_log_entry("app", V, "w", entry(i))
    del pod
    snapshot_storage_buffered.close_all()
    assert _values() == [0, 1, 2]
