"""A writer id given to the stream helpers names the stream they write
(plan 38 A5): on one record copy the supervisor and the run it lends to its
child append to two streams, each with one appending process."""
import pytest
from stream_fakes import APP, V, StreamRecorder

from vmn_exp.core.streams import guest_writer_id
from vmn_exp.core.writer import (
    append_entries_to_log,
    append_metric_entries,
    create_log_entry,
    own_stream,
    set_default_writer_id,
    sync_to_remote,
)
from vmn_exp.core.real_io import real_io

GUEST = guest_writer_id("host")


@pytest.fixture
def host(monkeypatch):
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    set_default_writer_id(real_io().env, "host")


def _metrics(**values):
    return create_log_entry("metrics", values=values)


def test_supervisor_and_guest_on_one_copy_append_to_different_streams(host):
    copy = StreamRecorder(owner="o1")

    append_metric_entries(copy, APP, V, [_metrics(loss=1.0)])
    append_metric_entries(copy, APP, V, [_metrics(loss=0.5)], writer=GUEST)

    assert copy.metric_blocks == ["host~o1", "host-sdk~o1"]


def test_own_stream_asks_the_storage_for_the_given_writers_owner(host):
    copy = StreamRecorder(owner="o7")

    assert own_stream(copy, APP, V, writer=GUEST) == "host-sdk~o7"
    assert copy.owner_asked == [GUEST]


def test_own_stream_without_a_writer_is_unchanged(host):
    copy = StreamRecorder(owner="o7")

    assert own_stream(copy, APP, V) == "host~o7"
    assert copy.owner_asked == ["host"]


def test_metric_and_log_entries_with_a_writer_go_to_that_writers_streams(host):
    copy = StreamRecorder()

    append_entries_to_log(copy, APP, V, [_metrics(acc=0.9), create_log_entry("note", text="hi")],
                          writer=GUEST)

    assert copy.metric_blocks == ["host-sdk~o1"]
    assert [stream for stream, _ in copy.log_entries] == ["host-sdk~o1"]


def test_sync_to_remote_with_a_writer_names_that_writers_stream(host):
    copy = StreamRecorder()

    sync_to_remote(copy, APP, V, writer=GUEST)

    assert copy.synced == [("log", "host-sdk~o1"), ("metrics", "host-sdk~o1")]
