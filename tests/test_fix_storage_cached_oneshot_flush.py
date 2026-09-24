"""A one-shot log append (``vmn exp tag``, ``vmn exp add --note``, the
``metrics`` entry ``vmn exp create --metrics`` writes) has no run supervisor
or SDK heartbeat thread left to flush it to the remote later: the call site
must flush it itself, right after appending (see
``version_stamp.core.experiment_writer.flush_log`` and its callers:
``tag_run``, ``experiment_create``, ``experiment_add``).

A live run's heartbeat loop ships new bytes on its own schedule -- an append
made while one is running (``append_to_log`` from the metrics tailer/SDK) must
keep batching, i.e. must not reach the remote before something explicitly
syncs it.
"""
import pytest
from s3_helpers import cached_host, entry, meta, mocked_bucket, s3_storage

from version_stamp.core.experiment_manage import tag_run
from version_stamp.core.experiment_writer import append_to_log, create_log_entry, flush_log


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def test_tag_run_reaches_the_remote_with_no_heartbeat(tmp_path):
    """``vmn exp tag``/``version_stamp.exp.manage.set_tags`` on a run with no
    live supervisor -- the tag must not be stranded in the local cache."""
    host = cached_host(tmp_path, "a")
    host.save("app", "v1", meta("v1"), {})

    assert tag_run(host, "app", "v1", tags={"verdict": "keep"})

    # A second host / a fresh read of the bucket only, simulating another
    # machine or this host's local cache having been cleared.
    remote_only = s3_storage()
    log = remote_only.load_merged_log("app", "v1")
    tag_entries = [e for e in log if e["type"] == "tags"]
    assert tag_entries and tag_entries[0]["set"] == {"verdict": "keep"}


def test_create_metrics_flush_reaches_the_remote_with_no_heartbeat(tmp_path):
    """``vmn exp create --metrics``: the metrics entry is logged before any
    run ever starts, so its caller must flush it itself (see
    ``experiment_create`` in ``version_stamp.cli.experiment``)."""
    host = cached_host(tmp_path, "a")
    host.save("app", "v1", meta("v1"), {})

    append_to_log(host, "app", "v1", create_log_entry("metrics", values={"i": 0}))
    flush_log(host, "app", "v1")

    remote_only = s3_storage()
    log = remote_only.load_merged_log("app", "v1")
    assert [e["values"]["i"] for e in log if e["type"] == "metrics"] == [0]


def test_append_to_log_alone_does_not_reach_the_remote(tmp_path):
    """The live-run path (the metrics tailer, the SDK) appends via
    ``append_to_log`` without flushing on every call -- its own heartbeat loop
    syncs on its own schedule. Batching must stay intact: an append with no
    explicit flush must not show up on a remote-only read yet."""
    host = cached_host(tmp_path, "a")
    host.save("app", "v1", meta("v1"), {})

    append_to_log(host, "app", "v1", entry(0))

    remote_only = s3_storage()
    assert remote_only.load_merged_log("app", "v1") == []
