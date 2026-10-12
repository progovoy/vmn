"""A record copy is the physical directory, not the path that reached it:
one directory seen through two paths (a symlink, a bind mount, macOS /tmp vs
/private/tmp) is one copy with one owner; a copy that lands back at the
original's path (a backup restored, an rsync on a host sharing the writer id)
is another directory and mints its own owner. Two processes that disagree
about one directory's identity (a container's st_dev) leave no stream
unshipped."""
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
    tag_keys,
)
from s3_helpers import cached_host, meta
from vmn_exp.storage import stream_owner


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _ship(h):
    s = stream(h)
    h.sync_log_to_remote(APP, V, s)
    h.sync_metrics_to_remote(APP, V, s)


def _append(h, step, key):
    h.append_log_entry(APP, V, stream(h), tag(step, key))
    h.append_metric_block(APP, V, stream(h), block(float(step), start=step * 10))


def _linked(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    os.symlink(str(tmp_path / "a"), str(tmp_path / "alink"))
    return a


def test_two_paths_to_one_root_share_its_stream_and_lose_nothing(tmp_path):
    a = _linked(tmp_path)
    b = cached_host(tmp_path, "alink")
    _append(a, 1, "k1")
    _append(b, 2, "k2")
    _append(a, 3, "k3")

    for h in (a, b, a):
        _ship(h)

    assert stream(a) == stream(b)
    assert remote_tag_keys() == ["k1", "k2", "k3"]
    assert remote_metric_values() == [1.0, 2.0, 3.0]


def test_an_unshipped_line_survives_another_path_opening_the_root(tmp_path):
    a = _linked(tmp_path)
    _append(a, 1, "k1")
    b = cached_host(tmp_path, "alink")
    _append(b, 2, "k2")
    _ship(b)

    _ship(a)

    assert remote_tag_keys() == ["k1", "k2"]
    assert remote_metric_values() == [1.0, 2.0]


def test_a_backup_restored_at_the_same_path_loses_nothing(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    _append(a, 1, "k1")
    _ship(a)
    shutil.copytree(tmp_path / "a", tmp_path / "backup")
    _append(a, 2, "k2")
    _ship(a)
    before = stream(a)
    shutil.rmtree(tmp_path / "a")
    shutil.copytree(tmp_path / "backup", tmp_path / "a")  # restore
    shutil.rmtree(tmp_path / "backup")
    a = cached_host(tmp_path, "a")
    _append(a, 3, "k3")

    _ship(a)

    assert stream(a) != before
    assert remote_tag_keys() == ["k1", "k2", "k3"]
    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert tag_keys(a.load_merged_log(APP, V)) == ["k1", "k2", "k3"]
    assert metric_values(a) == [1.0, 2.0, 3.0]


def test_processes_disagreeing_on_a_roots_identity_leave_no_stream_unshipped(
        tmp_path, monkeypatch):
    real = getattr(stream_owner, "_identity", None)

    def container_view(path):  # "alink" is the same dir seen with another st_dev
        dev, ino = real(path)
        return [dev + 1, ino] if "alink" in str(path) else [dev, ino]

    monkeypatch.setattr(stream_owner, "_identity", container_view, raising=False)
    a = _linked(tmp_path)
    b = cached_host(tmp_path, "alink")
    _append(a, 1, "k1")
    _append(b, 2, "k2")
    _ship(b)
    _append(a, 3, "k3")
    _ship(a)
    _append(b, 4, "k4")
    _append(a, 5, "k5")

    for h in (b, a, b, a):
        _ship(h)

    assert remote_tag_keys() == ["k1", "k2", "k3", "k4", "k5"]
    assert remote_metric_values() == [1.0, 2.0, 3.0, 4.0, 5.0]
