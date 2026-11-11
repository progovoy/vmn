"""Plan 40 C5: a log buffer lives under the buffers dir it is given and,
once written to, carries an owner marker and holds its owner lock for as
long as its process owns it."""
import gc
import json
import os
import socket
import weakref

import pytest
from deferred_ship_fakes import FakeBucket
from s3_helpers import entry, meta

from vmn_exp.storage import buffer_owner, buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.local import LocalSnapshotStorage

fcntl = pytest.importorskip("fcntl")

APP, V, W = "app", "v", "w"


@pytest.fixture(autouse=True)
def _flush_at_end():
    yield
    buffered.close_all()


@pytest.fixture
def bucket(tmp_path):
    remote = FakeBucket(str(tmp_path / "bucket"))
    remote.save(APP, V, meta(V), {})
    return remote


@pytest.fixture
def buffers(tmp_path):
    return str(tmp_path / "buffers")


@pytest.fixture
def pod(bucket, buffers):
    return BufferedRemoteStorage(bucket, buffers, area="runs")


def _marker(root):
    with open(os.path.join(root, buffer_owner.MARKER_FILE)) as f:
        return json.load(f)


def _lockable(root):
    """Whether another holder could take *root*'s owner lock now."""
    fd = os.open(os.path.join(root, buffer_owner.LOCK_FILE), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def _keep(monkeypatch, pod):
    """Close *pod* while the store is out of reach: its buffer is kept."""
    pod.append_log_entry(APP, V, W, entry(0))  # the first ships at once
    pod.append_log_entry(APP, V, W, entry(1))  # not due: buffered
    root = pod._buffer_root
    with monkeypatch.context() as m:
        m.setattr(pod, "_ship", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
        pod.close()
    return root


def test_the_buffer_root_is_under_the_given_buffers_dir(pod, buffers):
    pod.append_log_entry(APP, V, W, entry(0))
    assert os.path.dirname(pod._buffer_root) == buffers


def test_reads_still_create_no_buffer_dir(pod, buffers):
    pod.list_snapshots(APP)
    pod.load_record(APP, V)
    assert not os.path.exists(buffers)


def test_the_first_append_writes_the_owner_marker(pod, bucket):
    pod.append_log_entry(APP, V, W, entry(0))
    marker = _marker(pod._buffer_root)
    assert marker["pid"] == os.getpid()
    assert marker["host"] == socket.gethostname()
    assert marker["started_at"]
    assert marker["remote"] == repr(bucket.cache_identity())
    assert marker["area"] == "runs"


def test_a_live_buffer_holds_its_owner_lock(pod):
    pod.append_log_entry(APP, V, W, entry(0))
    assert not _lockable(pod._buffer_root)


def test_a_kept_buffer_releases_its_owner_lock(monkeypatch, pod):
    root = _keep(monkeypatch, pod)
    assert os.path.isdir(root) and pod._buffer_root != root
    assert _lockable(root)


def test_a_dropped_storage_releases_its_owner_lock(bucket, buffers):
    pod = BufferedRemoteStorage(bucket, buffers, area="runs")
    pod.append_log_entry(APP, V, W, entry(0))  # ships at once: nothing pending
    root = pod._buffer_root
    ref = weakref.ref(pod)
    del pod
    gc.collect()
    assert ref() is None
    assert _lockable(root)


def test_another_areas_storage_buffers_under_the_same_dir(pod, buffers):
    other = pod.in_area("snapshots")
    assert os.path.dirname(other._buffer_root) == buffers


def test_a_childs_buffer_gets_its_own_marker(pod):
    pod.append_log_entry(APP, V, W, entry(0))
    parents = pod._buffer_root
    pod._pid = -1  # what a forked child sees: the buffer is its parent's
    pod.append_log_entry(APP, V, W, entry(1))
    assert pod._buffer_root != parents
    assert _marker(pod._buffer_root)["pid"] == os.getpid()
    assert not _lockable(pod._buffer_root)


def test_a_forked_child_closes_the_inherited_owner_lock(pod):
    pod.append_log_entry(APP, V, W, entry(0))
    root = pod._buffer_root
    lock = pod._local.owner_lock
    parents_fd = os.dup(lock.fd)  # the parent's copy of the same open file
    try:
        buffer_owner._close_inherited()  # what the after-fork hook runs in a child
        assert lock.fd is None
        assert not _lockable(root)  # the parent's copy still holds it
        lock.release()  # the child's release closes nothing more
    finally:
        os.close(parents_fd)
    assert _lockable(root)


def test_reopen_takes_the_existing_streams_without_a_new_owner_or_lock(monkeypatch, pod,
                                                                        bucket):
    root = _keep(monkeypatch, pod)
    kept_streams = set(LocalSnapshotStorage(root, "runs").log_sizes(APP, V))

    reopened = BufferedRemoteStorage.reopen(root, bucket, "runs")
    reopened.sync_log_to_remote(APP, V, W)

    assert set(bucket.log_sizes(APP, V)) == kept_streams
    assert [e["values"]["i"] for e in bucket.load_merged_log(APP, V)] == [0, 1]
    assert reopened not in buffered._PENDING
    assert _lockable(root)
    assert os.path.isdir(root)  # its shipper decides when it goes
