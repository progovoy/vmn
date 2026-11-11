"""The sdk-side classes that time things take their clock from the caller:
none falls back to the real one (plan 44 G11 Part A)."""
import pytest
from fakes.clock import FakeClock

from vmn_exp.core.alerts.config import AlertConfig
from vmn_exp.core.alerts.dispatch import Alerter
from vmn_exp.core.index_vmx_check import VmxCheck
from vmn_exp.core.journal_keys import decode_key
from vmn_exp.core.metric_block import decode_blocks
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.output_log import OutputArtifact
from vmn_exp.reports.index import ReportIndex
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.local import LocalSnapshotStorage


class BlockSink:
    def __init__(self):
        self.blocks = []

    def append_metric_block(self, app, verstr, writer, data):
        self.blocks.append(data)
        return True


class KeySink:
    def __init__(self):
        self.keys = []

    def put(self, key):
        self.keys.append(key)


class UploadCounter:
    def __init__(self):
        self.uploads = 0

    def save_artifact_file(self, *args, **kwargs):
        self.uploads += 1


def _wall(clock):
    return lambda: clock.now().timestamp()


@pytest.mark.parametrize("build", [
    lambda: MetricWriter(BlockSink(), "app", "v", "w"),
    lambda: OutputArtifact(UploadCounter(), "app", "v", 1024),
    lambda: Alerter(AlertConfig()),
    lambda: VmxCheck(lambda: None, "app"),
    lambda: ReportIndex(None),
], ids=["metric_writer", "output_artifact", "alerter", "vmx_check", "report_index"])
def test_a_clocked_class_built_without_a_clock_is_a_type_error(build):
    with pytest.raises(TypeError):
        build()


def test_journaled_without_a_clock_is_a_type_error(tmp_path):
    with pytest.raises(TypeError):
        journaled(LocalSnapshotStorage(str(tmp_path), "runs"), sink=KeySink())


def test_metric_stream_stamps_blocks_with_the_given_clock():
    clock, sink = FakeClock(), BlockSink()
    writer = MetricWriter(sink, "app", "v", "w", clock=_wall(clock))
    writer.add("loss", 0.5)
    writer.flush()
    [block] = decode_blocks(sink.blocks[0])
    assert list(block.keys["loss"].ts) == [int(clock.now().timestamp() * 1_000_000)]


def test_output_log_throttles_on_the_given_clock():
    clock, storage = FakeClock(), UploadCounter()
    artifact = OutputArtifact(storage, "app", "v", 1 << 20, clock=clock.monotonic)
    artifact.write(b"x" * 1000)
    assert artifact.upload()
    artifact.write(b"y")
    assert not artifact.upload()
    clock.advance(60)
    assert artifact.upload()
    assert storage.uploads == 2


def test_alert_dispatch_cooldown_follows_the_given_clock():
    clock = FakeClock()
    alerter = Alerter(AlertConfig(), clock=clock.monotonic)
    assert alerter.admit("stuck", wait_sec=30)
    clock.advance(29)
    assert not alerter.admit("stuck", wait_sec=30)
    clock.advance(1)
    assert alerter.admit("stuck", wait_sec=30)


def test_report_index_full_sweep_is_due_after_full_sweep_sec(tmp_path):
    clock = FakeClock()
    storage = journaled(LocalSnapshotStorage(str(tmp_path), "runs"), clock=_wall(clock))
    index = ReportIndex(storage, clock=_wall(clock), full_sweep_sec=100)
    index.refresh()
    clock.advance(99)
    assert not index._sweep_due()
    clock.advance(1)
    assert index._sweep_due()


def test_journal_follower_reads_the_given_clock(tmp_path):
    clock, sink = FakeClock(), KeySink()
    store = journaled(LocalSnapshotStorage(str(tmp_path), "runs"), sink=sink,
                      writer_id="w", clock=_wall(clock))
    store.create_exclusive("app", "v1", {"verstr": "v1"}, {})
    [key] = sink.keys
    assert decode_key(key).unix_ms == int(clock.now().timestamp() * 1000)
