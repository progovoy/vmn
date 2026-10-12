"""Streams a record copy inherited (a ``cp -r``, a restore, a move across
filesystems) are never shipped, pushed nor compacted automatically: only
their owner does that. A sync or a push notes on stderr when the remote lacks
some of them; an explicit adopt (``vmn-exp push --adopt``) makes the copy
their owner — after catching its files up with what the remote holds — and
they are shipped from then on."""
import logging
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
    tag_keys,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.adopt import adopt_streams, missing_inherited
from vmn_exp.core.metric_compact import compact_record
from vmn_exp.core.push_logs import push_logs
from vmn_exp.core.push_metrics import push_metrics
from vmn_exp.core.writer import own_stream
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _ship(h, own=None):
    own = own or stream(h)
    h.sync_log_to_remote(APP, V, own)
    h.sync_metrics_to_remote(APP, V, own)


def _move(tmp_path, src, dst):
    shutil.copytree(tmp_path / src, tmp_path / dst)  # a move across filesystems
    shutil.rmtree(tmp_path / src)


def _original_with_unshipped(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    _ship(a, own)
    a.append_log_entry(APP, V, own, tag(2, "k2"))
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    return own


def _notes(caplog):
    return [r.getMessage() for r in caplog.records if "--adopt" in r.getMessage()]


def test_a_moved_copy_ships_its_inherited_streams_only_once_adopted(tmp_path, caplog):
    old = _original_with_unshipped(tmp_path)
    _move(tmp_path, "a", "b")
    b = cached_host(tmp_path, "b")

    with caplog.at_level(logging.WARNING):
        _ship(b)
        _ship(b)

    assert remote_tag_keys() == ["k1"] and remote_metric_values() == [1.0]
    notes = _notes(caplog)
    assert len(notes) == 1 and V in notes[0]
    assert b.adopt_streams(APP, V) == [old.partition("~")[2]]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _ship(b)
    assert _notes(caplog) == []
    assert remote_tag_keys() == ["k1", "k2"]
    assert remote_metric_values() == [1.0, 2.0]
    compact_record(b, APP, V)
    assert remote_metric_values() == [1.0, 2.0]


def test_adopting_catches_up_with_what_the_original_shipped_after_the_copy(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    _ship(a, own)
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    a.append_log_entry(APP, V, own, tag(2, "k2"))
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    _ship(a, own)
    shutil.rmtree(tmp_path / "a")
    b = cached_host(tmp_path, "b")
    b.append_metric_block(APP, V, stream(b), block(3.0, start=3))

    assert b.adopt_streams(APP, V)
    _ship(b)
    compact_record(b, APP, V)
    push_logs(b._local, s3_storage(), APP, V, finished=True)
    push_metrics(b._local, s3_storage(), APP, V)

    assert remote_tag_keys() == ["k1", "k2"]
    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0, 3.0]
    assert tag_keys(cached_host(tmp_path, "b").load_merged_log(APP, V)) == ["k1", "k2"]


def test_adopting_a_stream_the_original_compacted_keeps_every_point(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    _ship(a, own)
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    _ship(a, own)
    assert compact_record(a, APP, V) == [own]
    shutil.rmtree(tmp_path / "a")
    b = cached_host(tmp_path, "b")

    assert b.adopt_streams(APP, V)
    b.append_metric_block(APP, V, stream(b), block(3.0, start=3))
    _ship(b)
    compact_record(b, APP, V)
    push_metrics(b._local, s3_storage(), APP, V)

    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0, 3.0]


def test_an_offline_copy_pushes_inherited_streams_only_once_adopted(tmp_path):
    s3_storage().create_exclusive(APP, V, meta(V), {})
    a = LocalSnapshotStorage(str(tmp_path / "a"), "runs")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = own_stream(a, APP, V)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    _move(tmp_path, "a", "b")
    b, target = LocalSnapshotStorage(str(tmp_path / "b"), "runs"), s3_storage()

    push_logs(b, target, APP, V)
    push_metrics(b, target, APP, V)
    assert remote_tag_keys() == [] and remote_metric_values() == []
    assert missing_inherited(b, target, APP, V) == [own]

    assert adopt_streams(b, target, APP, V) == [own.partition("~")[2]]
    push_logs(b, target, APP, V)
    push_metrics(b, target, APP, V)

    assert missing_inherited(b, target, APP, V) == []
    assert remote_tag_keys() == ["k1"] and remote_metric_values() == [1.0]


def test_a_root_without_inherited_streams_has_nothing_to_adopt(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    a.append_log_entry(APP, V, stream(a), tag(1, "k1"))

    assert a.adopt_streams(APP, V) == []
    assert missing_inherited(a._local, s3_storage(), APP, V) == []
