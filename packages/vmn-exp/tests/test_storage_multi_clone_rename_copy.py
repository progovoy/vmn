"""Round-5 repro: an original renamed on its filesystem (it keeps its owner)
and a ``cp -r`` copy of it, made before or after the rename. The copy never
ships, pushes nor compacts the original's stream — whatever it can tell about
the original — so the renamed original stays its one shipper and nothing is
ever duplicated, even when the original compacts while the copy ships."""
import json
import os
import shutil

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    remote_metric_values,
    remote_tag_keys,
    stream,
    tag,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.metric_compact import compact_record
from vmn_exp.core.push_logs import push_logs
from vmn_exp.core.push_metrics import push_metrics
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.stream_owner import OWNER_FILE

_WRITES = ("create_metric_segment", "create_log_segment", "put_indexed",
           "save_file", "compact_log_segments")


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _rename_then_copy(tmp_path):
    os.rename(tmp_path / "a", tmp_path / "a2")
    shutil.copytree(tmp_path / "a2", tmp_path / "c")


def _copy_then_rename(tmp_path):
    shutil.copytree(tmp_path / "a", tmp_path / "c")
    os.rename(tmp_path / "a", tmp_path / "a2")


ORDERS = [_rename_then_copy, _copy_then_rename]


def _setup(tmp_path, order):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    s = stream(a)
    a.append_log_entry(APP, V, s, tag(1, "k1"))
    a.append_metric_block(APP, V, s, block(1.0, start=1))
    a.sync_log_to_remote(APP, V, s)
    a.sync_metrics_to_remote(APP, V, s)
    a.append_log_entry(APP, V, s, tag(2, "k2"))  # unshipped
    a.append_metric_block(APP, V, s, block(2.0, start=2))
    order(tmp_path)
    return s


def _watch_writes(target, s, hook=None):
    """Record every remote write *target* makes to stream *s*."""
    writes = []
    for name in _WRITES:
        real = getattr(target, name, None)
        if real is None:
            continue

        def call(*args, _real=real, _name=name, **kw):
            if s in args or any(s in str(a) for a in args):
                writes.append(_name)
                if hook:
                    hook()
            return _real(*args, **kw)

        setattr(target, name, call)
    return writes


@pytest.mark.parametrize("order", ORDERS)
def test_the_copy_never_ships_the_renamed_originals_stream(tmp_path, order):
    s = _setup(tmp_path, order)
    a2 = cached_host(tmp_path, "a2")
    assert stream(a2) == s
    c = cached_host(tmp_path, "c")
    assert stream(c) != s
    c.append_metric_block(APP, V, stream(c), block(3.0, start=3))
    c.append_log_entry(APP, V, stream(c), tag(3, "k3"))
    writes = _watch_writes(c._remote, s,
                           hook=lambda: compact_record(cached_host(tmp_path, "a2"), APP, V))

    for _ in range(2):
        c.sync_log_to_remote(APP, V, stream(c))
        c.sync_metrics_to_remote(APP, V, stream(c))
        compact_record(c, APP, V)

    assert writes == []
    a2 = cached_host(tmp_path, "a2")
    a2.sync_log_to_remote(APP, V, s)
    a2.sync_metrics_to_remote(APP, V, s)
    compact_record(a2, APP, V)
    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert remote_tag_keys() == ["k1", "k2", "k3"]
    for host in ("a2", "c"):
        assert metric_values(cached_host(tmp_path, host)) == [1.0, 2.0, 3.0], host


@pytest.mark.parametrize("order", ORDERS)
def test_a_push_from_the_copy_never_pushes_the_renamed_originals_stream(tmp_path, order):
    s = _setup(tmp_path, order)
    local = LocalSnapshotStorage(str(tmp_path / "c"), "runs")
    target = s3_storage()
    writes = _watch_writes(target, s,
                           hook=lambda: compact_record(cached_host(tmp_path, "a2"), APP, V))

    push_logs(local, target, APP, V, finished=True)
    push_metrics(local, target, APP, V)
    compact_record(local, APP, V)

    assert writes == []
    a2 = cached_host(tmp_path, "a2")
    a2.sync_metrics_to_remote(APP, V, s)
    compact_record(a2, APP, V)
    assert remote_metric_values() == [1.0, 2.0]


def test_a_renamed_original_records_its_new_path(tmp_path):
    _setup(tmp_path, _rename_then_copy)
    a2 = cached_host(tmp_path, "a2")
    stream(a2)

    with open(os.path.join(a2._local.local_record_dir(APP, V), OWNER_FILE)) as f:
        found = json.load(f)
    assert found["path"] == os.path.realpath(a2._local.local_record_dir(APP, V))
