"""The run ``vmn-exp run``'s child adopts (plan 38 A5) is a guest on the
supervisor's record: it appends to a stream of its own and never writes the
run's state, its ``run`` entry or its finish alerts."""
import logging

import pytest
from stream_fakes import APP, V, StreamRecorder

from vmn_exp.core.real_io import RealClock, RealHost, RealRandom
from vmn_exp.core.streams import guest_writer_id
from vmn_exp.core.writer import set_default_writer_id
from vmn_exp.sdk import run as run_module
from vmn_exp.sdk.guest_run import GuestRun
from vmn_exp.sdk.run import Run

GUEST = guest_writer_id("host")


@pytest.fixture(autouse=True)
def host(monkeypatch):
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    set_default_writer_id("host")


@pytest.fixture
def compacted(monkeypatch):
    streams = []
    monkeypatch.setattr(run_module, "compact_by",
                        lambda storage, app, verstr, stream, deadline: streams.append(stream))
    return streams


class _AlertSpy(GuestRun):
    alerts = 0

    def _finish_alerts(self, timeout):
        type(self).alerts += 1


def _open(storage, cls=GuestRun, **kwargs):
    kwargs.setdefault("writer", GUEST)
    run = cls(storage, APP, V, 3600, sync_interval_sec=0, export_env=False,
              install_hooks=None, clock=RealClock(), host=RealHost(), random=RealRandom(), **kwargs)
    run._open()
    return run


def test_guest_appends_metrics_to_the_guest_stream_of_the_adopted_run(compacted):
    copy = StreamRecorder()
    run = _open(copy)

    run.log_metric("loss", 0.5)
    run.finish()

    assert copy.metric_blocks == ["host-sdk~o1"]


def test_guest_never_writes_run_state_on_open_heartbeat_finish_or_release(compacted):
    finished, released = StreamRecorder(), StreamRecorder()

    run = _open(finished)
    run._beat()
    run.finish(exit_code=3)
    _open(released).release(reason="preempted")

    assert finished.state_saves == [] and released.state_saves == []


def test_a_plain_run_on_the_same_fake_does_write_its_state(compacted):
    copy = StreamRecorder()

    _open(copy, cls=Run, writer=None).finish()

    assert copy.state_saves


def test_guest_finish_writes_no_run_entry_and_fires_no_alerts(compacted):
    copy = StreamRecorder()

    _open(copy, cls=_AlertSpy).finish(exit_code=2)

    assert copy.entries_of("run") == []
    assert _AlertSpy.alerts == 0


def test_guest_finish_with_error_records_the_error_entry(compacted):
    copy = StreamRecorder()

    _open(copy).finish(exit_code=1, error=RuntimeError("diverged"))

    ((stream, entry),) = copy.entries_of("error")
    assert stream == "host-sdk~o1"
    assert entry["exception"] == "RuntimeError" and "diverged" in entry["message"]


def test_guest_syncs_and_compacts_only_its_own_stream(compacted):
    copy = StreamRecorder()
    run = _open(copy)
    run.log_metric("acc", 0.9)

    run.finish()

    assert copy.synced and {stream for _, stream in copy.synced} == {"host-sdk~o1"}
    assert compacted == ["host-sdk~o1"]


def test_guest_warns_that_name_is_ignored(compacted, caplog):
    with caplog.at_level(logging.WARNING, logger="vmn_exp.sdk.guest_run"):
        run = _open(StreamRecorder(), name="my-name")
    run.finish()

    assert run.name is None
    assert "vmn-exp run --name" in caplog.text


def test_guest_ignores_capture_output(compacted):
    run = _open(StreamRecorder(), capture_output=True)
    run.finish()

    assert run._output is None


def test_a_run_without_a_writer_passes_no_writer_argument(monkeypatch, compacted):
    synced = []
    monkeypatch.setattr(run_module, "sync_to_remote", lambda *args: synced.append(args))
    copy = StreamRecorder()

    _open(copy, cls=Run, writer=None).finish()

    assert synced == [(copy, APP, V)]
    assert compacted == ["host~o1"]
