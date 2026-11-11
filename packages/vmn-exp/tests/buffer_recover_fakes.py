"""Fakes for shipping kept log buffers (plan 40 C6): a tmp_path bucket that
records its ships, a host whose lock and removal are fakes, and a buffer
kept by a close that could not reach the store."""
import os
import socket

from deferred_ship_fakes import FakeBucket
from s3_helpers import entry

from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.storage.buffer_host import LocalBufferHost
from vmn_exp.storage.buffered import BufferedRemoteStorage

APP, V, W = "app", "v", "w"


class RecordingBucket(FakeBucket):
    def __init__(self, root, events):
        super().__init__(root)
        self.events = events

    def _create(self, *args):
        self.events.append("ship")
        return super()._create(*args)


class FakeLock:
    def __init__(self, events):
        self.events = events
        self.released = False

    def release(self):
        if not self.released:
            self.released = True
            self.events.append("release")


class FakeHost(LocalBufferHost):
    """The real listing (on tmp_path); a fake lock and removal."""

    def __init__(self, events, refuse=False, here=None, network=False):
        self.events = events
        self.removed = []
        self.refuse = refuse
        self.here = here or socket.gethostname()
        self.network = network

    def try_lock(self, root):
        if self.refuse:
            return None
        self.events.append("lock")
        return FakeLock(self.events)

    def remove_tree(self, root):
        self.events.append("remove")
        self.removed.append(root)

    def hostname(self):
        return self.here

    def on_network_fs(self, path):
        return self.network


class NoCalls:
    """A remote that must not be touched."""

    def __getattr__(self, name):
        raise AssertionError(f"the remote was called: {name}")


def down(*args, **kwargs):
    raise ConnectionError("the store is out of reach")


def _block(value):
    return encode_block({"x": Columns([0], [0], [value])})


def kept_buffer(monkeypatch, bucket, base):
    """A buffer under *base* closed while *bucket* was out of reach: one log
    line and one metric block shipped, one of each kept. Its root."""
    pod = BufferedRemoteStorage(bucket, os.path.join(base, "store"), area="runs")
    pod.append_log_entry(APP, V, W, entry(0))  # the first ships at once
    pod.append_log_entry(APP, V, W, entry(1))
    pod.append_metric_block(APP, V, W, _block(1.0))
    pod.append_metric_block(APP, V, W, _block(2.0))
    root = pod._buffer_root
    with monkeypatch.context() as m:
        m.setattr(pod, "_ship", down)
        m.setattr(bucket, "create_metric_segment", down)
        pod.close()
    bucket.events.clear()
    return root


def remote_steps(bucket):
    """The log lines the remote holds (metric blocks merge in without an ``i``)."""
    return [e["values"]["i"] for e in bucket.load_merged_log(APP, V) if "i" in e["values"]]
