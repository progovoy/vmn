"""Plan 40 C6: list kept or orphaned log buffers and ship one only while
holding its owner lock (a tmp_path buffers base and bucket, a fake lock)."""
import os
import socket

import pytest
import yaml
from buffer_recover_fakes import (
    APP, V, FakeHost, NoCalls, RecordingBucket, down, kept_buffer, remote_steps,
)
from s3_helpers import meta

from vmn_exp.core import buffer_recover
from vmn_exp.core.buffer_recover import kept_buffers, ship_buffer
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage import buffered
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def _flush_at_end():
    yield
    buffered.close_all()


@pytest.fixture
def events():
    return []


@pytest.fixture
def bucket(tmp_path, events):
    remote = RecordingBucket(str(tmp_path / "bucket"), events)
    remote.save(APP, V, meta(V), {})
    return remote


@pytest.fixture
def base(tmp_path):
    return str(tmp_path / "log-buffers")


@pytest.fixture
def host(events):
    return FakeHost(events)


def _remote_metric_objects(bucket):
    return sum(len(objects) for objects in bucket.metric_objects(APP, V).values())


def _state(state, **kw):
    return yaml.dump(dict({"state": state, "attempt": "a1"}, **kw))


def _only(base, host):
    (buffer,) = kept_buffers([base], host)
    return buffer


def test_kept_buffers_lists_marker_fields_and_runs(monkeypatch, bucket, base, host):
    root = kept_buffer(monkeypatch, bucket, base)

    buffer = _only(base, host)

    assert buffer.root == root
    assert buffer.pid == os.getpid()
    assert buffer.host == socket.gethostname()
    assert buffer.started_at
    assert buffer.remote == repr(bucket.cache_identity())
    assert buffer.area == "runs"
    assert buffer.runs == [(APP, V)]
    assert buffer.size > 0
    assert buffer.live is False


def test_kept_buffers_probes_the_lock_and_releases_it_at_once(monkeypatch, bucket, base,
                                                               host, events):
    kept_buffer(monkeypatch, bucket, base)
    _only(base, host)
    assert events == ["lock", "release"]


def test_a_buffer_whose_lock_is_held_is_listed_as_live(monkeypatch, bucket, base, events):
    kept_buffer(monkeypatch, bucket, base)
    assert _only(base, FakeHost(events, refuse=True)).live is True


def test_ship_buffer_ships_unshipped_log_lines_and_metric_blocks(monkeypatch, bucket, base,
                                                                 host):
    kept_buffer(monkeypatch, bucket, base)
    assert remote_steps(bucket) == [0]
    blocks_before = _remote_metric_objects(bucket)

    outcome = ship_buffer(_only(base, host), bucket, host)

    assert outcome.status == buffer_recover.SHIPPED
    assert remote_steps(bucket) == [0, 1]
    assert _remote_metric_objects(bucket) > blocks_before


def test_shipping_twice_adds_nothing(monkeypatch, bucket, base, host):
    kept_buffer(monkeypatch, bucket, base)
    buffer = _only(base, host)
    ship_buffer(buffer, bucket, host)  # the fake removal leaves the dir

    ship_buffer(buffer, bucket, host)

    assert remote_steps(bucket) == [0, 1]


def test_a_final_state_in_the_buffer_replaces_the_remotes_running_state(
        monkeypatch, bucket, base, host):
    root = kept_buffer(monkeypatch, bucket, base)
    bucket.save_file(APP, V, RUN_STATE_FILE, _state("running"))
    LocalSnapshotStorage(root, "runs").save_file(
        APP, V, RUN_STATE_FILE, _state("finished", exit_code=0))

    assert ship_buffer(_only(base, host), bucket, host).status == buffer_recover.SHIPPED

    assert yaml.safe_load(bucket.load_file(APP, V, RUN_STATE_FILE))["state"] == "finished"


def test_a_buffer_without_a_final_state_leaves_the_remote_state_alone(
        monkeypatch, bucket, base, host):
    root = kept_buffer(monkeypatch, bucket, base)
    bucket.save_file(APP, V, RUN_STATE_FILE, _state("running", beat=2))
    LocalSnapshotStorage(root, "runs").save_file(APP, V, RUN_STATE_FILE, _state("running"))

    ship_buffer(_only(base, host), bucket, host)

    assert yaml.safe_load(bucket.load_file(APP, V, RUN_STATE_FILE))["beat"] == 2


def test_a_fully_shipped_buffer_is_removed(monkeypatch, bucket, base, host):
    root = kept_buffer(monkeypatch, bucket, base)
    ship_buffer(_only(base, host), bucket, host)
    assert host.removed == [root]


def test_keep_leaves_a_fully_shipped_buffer_in_place(monkeypatch, bucket, base, host):
    kept_buffer(monkeypatch, bucket, base)
    outcome = ship_buffer(_only(base, host), bucket, host, keep=True)
    assert outcome.status == buffer_recover.SHIPPED
    assert host.removed == []


def test_a_live_owners_buffer_is_neither_opened_nor_shipped(monkeypatch, bucket, base, events):
    kept_buffer(monkeypatch, bucket, base)
    host = FakeHost(events, refuse=True)

    outcome = ship_buffer(_only(base, host), NoCalls(), host)

    assert outcome.status == buffer_recover.LIVE
    assert host.removed == []


def test_the_owner_lock_is_held_for_the_whole_ship_and_released_after(
        monkeypatch, bucket, base, host, events):
    kept_buffer(monkeypatch, bucket, base)
    buffer = _only(base, host)
    events.clear()

    ship_buffer(buffer, bucket, host)

    assert events[0] == "lock" and "ship" in events
    last_ship = len(events) - 1 - events[::-1].index("ship")
    assert events[last_ship + 1:] == ["release", "remove"]


def test_a_failed_ship_keeps_the_buffer_and_reports_the_error(monkeypatch, bucket, base,
                                                              host, events):
    kept_buffer(monkeypatch, bucket, base)
    buffer = _only(base, host)
    events.clear()
    monkeypatch.setattr(bucket, "create_log_segment", down)

    outcome = ship_buffer(buffer, bucket, host)

    assert outcome.status == buffer_recover.FAILED
    assert "out of reach" in str(outcome.detail)
    assert host.removed == []
    assert events[-1] == "release"


def test_an_unpublished_final_state_fails_the_ship_and_keeps_the_buffer(
        monkeypatch, bucket, base, host):
    root = kept_buffer(monkeypatch, bucket, base)
    bucket.save_file(APP, V, RUN_STATE_FILE, _state("running", attempt="other"))
    LocalSnapshotStorage(root, "runs").save_file(APP, V, RUN_STATE_FILE, _state("finished"))

    outcome = ship_buffer(_only(base, host), bucket, host)

    assert outcome.status == buffer_recover.FAILED
    assert V in str(outcome.detail)
    assert host.removed == []


def test_a_dir_without_a_marker_is_listed_as_unknown_and_never_shipped_or_removed(
        base, host, events):
    stray = os.path.join(base, "store", "vmn-log-buffer-old")
    os.makedirs(stray)

    buffer = _only(base, host)
    outcome = ship_buffer(buffer, NoCalls(), host)

    assert buffer.live is None and buffer.root == stray
    assert outcome.status == buffer_recover.UNKNOWN
    assert events == [] and host.removed == []


def test_without_a_lock_primitive_nothing_is_shipped(monkeypatch, bucket, base, events):
    kept_buffer(monkeypatch, bucket, base)
    host = FakeHost(events)
    host.try_lock = None

    buffer = _only(base, host)
    outcome = ship_buffer(buffer, NoCalls(), host)

    assert buffer.live is None
    assert outcome.status == buffer_recover.NO_LOCK
    assert host.removed == []


def test_on_a_network_fs_another_hosts_buffer_counts_as_live(monkeypatch, bucket, base,
                                                             events):
    kept_buffer(monkeypatch, bucket, base)
    host = FakeHost(events, here="another-host", network=True)

    buffer = _only(base, host)
    outcome = ship_buffer(buffer, NoCalls(), host)

    assert buffer.live is True and "network filesystem" in buffer.why
    assert outcome.status == buffer_recover.LIVE
    assert events == []
