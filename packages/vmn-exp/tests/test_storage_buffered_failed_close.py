"""A buffered pod whose store is out of reach when it closes keeps its buffer
dir: it is the only copy of the lines and blocks that did not ship."""
import logging
import os
import tempfile

import pytest
import yaml
from s3_helpers import entry, meta, mocked_bucket, s3_storage

from vmn_exp.core.metric_block import decode_blocks, encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V, W = "app", "v", "w"
FINISHED = yaml.dump({"state": "finished"})


@pytest.fixture(autouse=True)
def _bucket(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # kept buffers go with the test
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


@pytest.fixture
def pod():
    remote = s3_storage()
    remote.save(APP, V, meta(V), {})
    return BufferedRemoteStorage(remote, area="runs")


def _unreachable(*args, **kwargs):
    raise ConnectionError("the store is out of reach")


def _cut_off(monkeypatch, pod):
    monkeypatch.setattr(pod, "_ship", _unreachable)
    monkeypatch.setattr(pod._remote, "create_metric_segment", _unreachable)


def _block(value):
    return encode_block({"x": Columns([0], [0], [value])})


def _buffered_steps(root):
    kept = LocalSnapshotStorage(root, "runs")
    return [e["values"]["i"] for e in kept.load_merged_log(APP, V)]


def _remote_steps():
    return [e["values"]["i"] for e in s3_storage().load_merged_log(APP, V)]


def _remote_blocks():
    remote = s3_storage()
    data = b"".join(
        remote.read_range(APP, V, name, 0, size)
        for objects in remote.metric_objects(APP, V).values()
        for name, size in objects
    )
    return [list(b.keys["x"].values) for b in decode_blocks(data)]


def _pod_with_unshipped_lines(monkeypatch, pod):
    for i in range(3):
        pod.append_log_entry(APP, V, W, entry(i))  # the first ships at once
    _cut_off(monkeypatch, pod)
    return pod._buffer_root


def test_close_keeps_the_buffer_when_the_last_log_lines_do_not_ship(monkeypatch, pod):
    root = _pod_with_unshipped_lines(monkeypatch, pod)

    pod.close()

    assert _remote_steps() == [0]
    assert _buffered_steps(root) == [0, 1, 2]


def test_close_keeps_the_buffer_when_the_last_metric_blocks_do_not_ship(monkeypatch, pod):
    pod.append_metric_block(APP, V, W, _block(1.0))  # ships at once
    pod.append_metric_block(APP, V, W, _block(2.0))
    root = pod._buffer_root
    _cut_off(monkeypatch, pod)

    pod.close()

    assert _remote_blocks() == [[1.0]]
    assert LocalSnapshotStorage(root, "runs").metric_objects(APP, V)


def test_the_warning_of_a_failed_close_names_the_kept_buffer(monkeypatch, pod, caplog):
    root = _pod_with_unshipped_lines(monkeypatch, pod)

    with caplog.at_level(logging.WARNING):
        pod.close()

    assert any(root in record.getMessage() for record in caplog.records)


def test_appends_after_a_failed_close_go_to_a_new_buffer(monkeypatch, pod):
    with monkeypatch.context() as outage:
        root = _pod_with_unshipped_lines(outage, pod)
        pod.append_log_entry(APP, V, own_stream(pod, APP, V), entry(3))
        kept_stream = own_stream(pod, APP, V)
        pod.close()

    pod.append_log_entry(APP, V, own_stream(pod, APP, V), entry(7))

    assert pod._buffer_root != root
    assert own_stream(pod, APP, V) != kept_stream
    assert _buffered_steps(root) == [0, 1, 2, 3]
    assert _remote_steps() == [0, 7]


def test_a_buffer_kept_by_a_failed_close_survives_the_exit_flush(monkeypatch, pod):
    root = _pod_with_unshipped_lines(monkeypatch, pod)
    pod.close()

    buffered.close_all()

    assert os.path.isdir(root)


def test_a_finished_runs_log_sync_keeps_metric_blocks_that_did_not_ship(monkeypatch, pod):
    with monkeypatch.context() as cut:
        cut.setattr(pod._remote, "create_metric_segment", _unreachable)
        pod.append_metric_block(APP, V, W, _block(1.0))  # the eager ship fails
    pod.save_file(APP, V, "run_state.yml", FINISHED)

    pod.sync_log_to_remote(APP, V, W)  # sync_to_remote ships logs, then metrics
    pod.sync_metrics_to_remote(APP, V, W)

    assert _remote_blocks() == [[1.0]]
