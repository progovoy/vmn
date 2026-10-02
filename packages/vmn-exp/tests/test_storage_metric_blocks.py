"""Metric streams on every backend (plan 12 §4.2): ``append_metric_block``,
``metric_objects``, ``read_range`` and ``put_indexed``."""
import pytest
from object_store_fakes import FakeContainerClient, FakeGCSClient
from s3_helpers import meta, mocked_bucket, s3_storage

from vmn_exp.core.metric_block import decode_blocks, encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import indexed_name, stream_name
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V, W = "app", "1.0.0-dev.abc.0001", "w"


def _block(*values):
    n = len(values)
    return encode_block({"x": Columns(list(range(n)), list(range(n)), list(values))})


def _gcs():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    return GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())


def _azure():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    return AzureSnapshotStorage("bkt", prefix="p", container=FakeContainerClient("bkt"))


@pytest.fixture
def bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


@pytest.fixture(params=["local", "s3", "gcs", "azure"])
def store(request, tmp_path, monkeypatch):
    if request.param == "s3":
        with mocked_bucket(monkeypatch):
            yield _saved(s3_storage())
        return
    make = {"local": lambda: LocalSnapshotStorage(str(tmp_path), "runs"),
            "gcs": _gcs, "azure": _azure}[request.param]
    yield _saved(make())


def _saved(storage):
    storage.save(APP, V, meta(V), {})
    return storage


def _read_all(storage, writer=W):
    data = b""
    for name, size in storage.metric_objects(APP, V)[writer]:
        data += storage.read_range(APP, V, name, 0, size)
    return [list(b.keys["x"].values) for b in decode_blocks(data)]


def test_blocks_round_trip(store):
    assert store.append_metric_block(APP, V, W, _block(1.0, 2.0))
    assert store.append_metric_block(APP, V, W, _block(3.0))
    assert _read_all(store) == [[1.0, 2.0], [3.0]]


def test_metric_objects_are_grouped_by_writer(store):
    store.append_metric_block(APP, V, "a", _block(1.0))
    store.append_metric_block(APP, V, "b", _block(2.0))
    assert set(store.metric_objects(APP, V)) == {"a", "b"}
    assert _read_all(store, "b") == [[2.0]]


def test_read_range_reads_a_slice(store):
    store.append_metric_block(APP, V, W, b"0123456789")
    [(name, size)] = store.metric_objects(APP, V)[W]
    assert size == 10
    assert store.read_range(APP, V, name, 3, 4) == b"3456"


def test_read_range_of_a_missing_object_is_none(store):
    assert store.read_range(APP, V, stream_name("nobody"), 0, 4) is None


def test_no_block_is_appended_to_a_missing_record(store):
    assert store.append_metric_block(APP, "gone", W, _block(1.0)) is False


def test_put_indexed_supersedes_the_writers_streams(store, tmp_path):
    store.append_metric_block(APP, V, W, _block(1.0))
    store.append_metric_block(APP, V, "other", _block(2.0))
    path = tmp_path / "w.vmx"
    path.write_bytes(b"VMSX-index")
    assert store.put_indexed(APP, V, W, str(path))
    objects = store.metric_objects(APP, V)
    assert objects[W] == [(indexed_name(W), 10)]
    assert store.read_range(APP, V, indexed_name(W), 0, 10) == b"VMSX-index"
    assert _read_all(store, "other") == [[2.0]]


def test_put_indexed_never_overwrites_an_indexed_file(store, tmp_path):
    first, second = tmp_path / "a.vmx", tmp_path / "b.vmx"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    assert store.put_indexed(APP, V, W, str(first))
    assert store.put_indexed(APP, V, W, str(second)) is False
    assert store.read_range(APP, V, indexed_name(W), 0, 6) == b"first"


def test_local_appends_truncate_a_torn_tail_first(tmp_path):
    store = _saved(LocalSnapshotStorage(str(tmp_path), "runs"))
    store.append_metric_block(APP, V, W, _block(1.0))
    path = tmp_path / "runs" / APP / V / stream_name(W)
    with open(path, "ab") as f:
        f.write(_block(9.0)[:-3])
    fresh = LocalSnapshotStorage(str(tmp_path), "runs")
    fresh.append_metric_block(APP, V, W, _block(2.0))
    assert _read_all(fresh) == [[1.0], [2.0]]
    assert path.stat().st_size == len(_block(1.0)) + len(_block(2.0))
