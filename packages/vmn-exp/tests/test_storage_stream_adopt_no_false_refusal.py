"""Adopt refuses only when the remote may lack a copy's points, never when it
holds them all: a ``.vmx`` the remote holds byte for byte (also one built
after a rewind), or a foreign ``.vmx`` followed by the owner's later
segments, covers the copy, so the note stays quiet and adopt goes ahead."""
import shutil

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    remote_metric_values,
    stream,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.adopt import missing_inherited
from vmn_exp.core.metric_compact import compact_record


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _move(tmp_path):
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    shutil.rmtree(tmp_path / "a")
    return cached_host(tmp_path, "b")


def _original(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    return a, stream(a)


def test_a_moved_run_compacted_after_a_rewind_is_adopted(tmp_path):
    a, own = _original(tmp_path)
    a.append_metric_block(APP, V, own, block(1.0, 2.0, 3.0, start=0))
    a.append_log_entry(APP, V, own, {"timestamp": "2099-01-01T00:00:00Z", "type": "rewind", "step": 1})
    a.sync_log_to_remote(APP, V, own)
    a.sync_metrics_to_remote(APP, V, own)
    assert compact_record(a, APP, V) == [own]
    a.sync_metrics_to_remote(APP, V, own)
    b = _move(tmp_path)
    assert missing_inherited(b._local, s3_storage(), APP, V) == []
    assert b.adopt_streams(APP, V)


def test_a_foreign_vmx_and_the_owners_later_segment_cover_the_copy(tmp_path):
    a, own = _original(tmp_path)
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    a.sync_metrics_to_remote(APP, V, own)
    compact_record(cached_host(tmp_path, "c"), APP, V)
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    a.sync_metrics_to_remote(APP, V, own)
    b = _move(tmp_path)
    assert missing_inherited(b._local, s3_storage(), APP, V) == []
    assert b.adopt_streams(APP, V)
    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0]


def test_a_moved_run_its_owner_compacted_is_adopted(tmp_path):
    a, own = _original(tmp_path)
    a.append_metric_block(APP, V, own, block(1.0, 2.0, start=0))
    a.sync_metrics_to_remote(APP, V, own)
    assert compact_record(a, APP, V) == [own]
    b = _move(tmp_path)
    assert missing_inherited(b._local, s3_storage(), APP, V) == []
    assert b.adopt_streams(APP, V)
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0]
    assert remote_metric_values() == [1.0, 2.0]
