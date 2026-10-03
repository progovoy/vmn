"""Metric streams of local-first and buffered storage (plan 12 §4.2): appends
land locally and ship as ``metrics/<w>@<seq>.vms`` segments on sync; every
write is journaled."""
import pytest
from s3_helpers import cached_host, meta, mocked_bucket, raw_keys, s3_storage

from vmn_exp.core.journal_keys import decode_key
from vmn_exp.core.metric_block import decode_blocks, encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import indexed_name, stream_name
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V, W = "app", "1.0.0-dev.abc.0001", "w"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _block(*values):
    n = len(values)
    return encode_block({"x": Columns(list(range(n)), list(range(n)), list(values))})


def _metric_keys():
    return sorted(k.split(f"/{V}/", 1)[1] for k in raw_keys() if "/metrics/" in k)


def _values(storage):
    data = b"".join(
        storage.read_range(APP, V, name, 0, size)
        for name, size in storage.metric_objects(APP, V)[W]
    )
    return [list(b.keys["x"].values) for b in decode_blocks(data)]


@pytest.fixture
def host(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    return host


def test_local_first_appends_stay_local_until_sync(host):
    host.append_metric_block(APP, V, W, _block(1.0))
    assert _metric_keys() == []
    host.sync_metrics_to_remote(APP, V, W)
    assert _metric_keys() == [stream_name(W)]


def test_each_sync_ships_the_new_blocks_as_a_segment(host):
    for i in range(3):
        host.append_metric_block(APP, V, W, _block(float(i)))
        host.sync_metrics_to_remote(APP, V, W)
    host.sync_metrics_to_remote(APP, V, W)
    assert _metric_keys() == [stream_name(W), stream_name(W, 1), stream_name(W, 2)]
    assert _values(s3_storage()) == [[0.0], [1.0], [2.0]]


def test_another_host_reads_the_shipped_blocks(host, tmp_path):
    host.append_metric_block(APP, V, W, _block(1.0))
    host.sync_metrics_to_remote(APP, V, W)
    other = cached_host(tmp_path, "b")
    assert _values(other) == [[1.0]]


def test_local_first_put_indexed_reaches_the_remote(host, tmp_path):
    host.append_metric_block(APP, V, W, _block(1.0))
    host.sync_metrics_to_remote(APP, V, W)
    path = tmp_path / "w.vmx"
    path.write_bytes(b"indexed")
    assert host.put_indexed(APP, V, W, str(path))
    assert _metric_keys() == [indexed_name(W)]
    assert host.metric_objects(APP, V)[W] == [(indexed_name(W), 7)]


def test_buffered_storage_ships_blocks_to_the_bucket():
    remote = s3_storage()
    remote.save(APP, V, meta(V), {})
    pod = BufferedRemoteStorage(remote, area="runs")
    pod.append_metric_block(APP, V, W, _block(1.0))
    pod.append_metric_block(APP, V, W, _block(2.0))
    pod.close()
    assert _values(remote) == [[1.0], [2.0]]
    assert _values(pod) == [[1.0], [2.0]]


class _Sink:
    def __init__(self):
        self.keys = []

    def put(self, key):
        self.keys.append(key)


def test_every_metric_write_is_journaled(tmp_path):
    sink = _Sink()
    store = journaled(LocalSnapshotStorage(str(tmp_path), "runs"), sink=sink,
                      writer_id="host_1", backoff=lambda attempt: None)
    store.save(APP, V, meta(V), {})
    before = len(sink.keys)
    store.append_metric_block(APP, V, W, _block(1.0))
    path = tmp_path / "w.vmx"
    path.write_bytes(b"indexed")
    store.put_indexed(APP, V, W, str(path))
    entries = [decode_key(k) for k in sink.keys[before:]]
    assert [e.name for e in entries] == [V, V]


def test_local_first_ships_the_blocks_appended_after_a_sealed_part(host, tmp_path):
    from vmn_exp.core.metric_files import part_name

    host.append_metric_block(APP, V, W, _block(1.0))
    host.append_metric_block(APP, V, W, _block(2.0))
    host.sync_metrics_to_remote(APP, V, W)
    path = tmp_path / "p.vmx"
    path.write_bytes(b"part")
    assert host.put_indexed(APP, V, W, str(path), part=1)
    assert _metric_keys() == [part_name(W, 1)]
    host.append_metric_block(APP, V, W, _block(3.0))
    host.sync_metrics_to_remote(APP, V, W)
    assert _metric_keys() == sorted([part_name(W, 1), stream_name(W)])
    remote = s3_storage()
    [(name, size)] = [o for o in remote.metric_objects(APP, V)[W] if o[0].endswith(".vms")]
    data = remote.read_range(APP, V, name, 0, size)
    assert [list(b.keys["x"].values) for b in decode_blocks(data)] == [[3.0]]
