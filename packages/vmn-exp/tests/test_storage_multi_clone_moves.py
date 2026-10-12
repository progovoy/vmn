"""A record whose ``.stream-owner`` names another directory — a ``cp -r``
copy, a checkout moved across filesystems, a copy whose original was deleted
later — never appends to
the recorded owner's streams: it mints its own owner and inherits the old
one's streams, whose local files never grow again. It ships just what the
remote lacks of them, so a delayed move loses nothing. Processes opening one
copy at once all end up with the same new owner."""
import random
import shutil
import threading
import time

import pytest
from multi_clone_helpers import (
    APP,
    LOG_CALLS,
    METRIC_CALLS,
    V,
    block,
    flaky,
    metric_values,
    one_host_bucket,
    quietly,
    remote_metric_values,
    remote_tag_keys,
    stream,
    tag,
    tag_keys,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.metric_compact import compact_record, compact_writer
from vmn_exp.core.push_metrics import push_metrics
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import stream_owner
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _ship(h, own):
    h.sync_log_to_remote(APP, V, own)
    h.sync_metrics_to_remote(APP, V, own)


def test_a_copy_whose_original_shipped_more_and_was_deleted_loses_nothing(tmp_path):
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
    ob = stream(b)
    b.append_log_entry(APP, V, ob, tag(3, "k3"))
    b.append_metric_block(APP, V, ob, block(3.0, start=3))

    _ship(b, ob)

    assert ob != own
    assert remote_tag_keys() == ["k1", "k2", "k3"]
    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert tag_keys(b.load_merged_log(APP, V)) == ["k1", "k2", "k3"]
    assert metric_values(b) == [1.0, 2.0, 3.0]


def _move_across_filesystems(src, dst):
    shutil.copytree(src, dst)  # what shutil.move does across devices
    shutil.rmtree(src)


def test_a_moved_copy_ships_what_its_original_never_did(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    _ship(a, own)
    a.append_log_entry(APP, V, own, tag(2, "k2"))
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    _move_across_filesystems(tmp_path / "a", tmp_path / "b")
    b = cached_host(tmp_path, "b")

    _ship(b, stream(b))

    assert stream(b) != own
    assert remote_tag_keys() == ["k1", "k2"]
    assert remote_metric_values() == [1.0, 2.0]


def test_a_root_renamed_on_its_filesystem_keeps_its_stream_and_ships_it(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    shutil.move(str(tmp_path / "a"), str(tmp_path / "b"))
    b = cached_host(tmp_path, "b")

    _ship(b, stream(b))

    assert stream(b) == own
    assert remote_tag_keys() == ["k1"]
    assert remote_metric_values() == [1.0]


def test_an_offline_copy_compacts_no_stream_it_inherited(tmp_path):
    s3_storage().create_exclusive(APP, V, meta(V), {})
    a = LocalSnapshotStorage(str(tmp_path / "a"), "runs")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = own_stream(a, APP, V)
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    push_metrics(a, s3_storage(), APP, V)
    b = LocalSnapshotStorage(str(tmp_path / "b"), "runs")

    assert compact_record(b, APP, V) == []
    push_metrics(b, s3_storage(), APP, V)

    assert remote_metric_values() == [1.0, 2.0]


def test_processes_opening_a_copy_at_once_share_one_new_owner(tmp_path, monkeypatch):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    a.append_log_entry(APP, V, stream(a), tag(0, "k0"))
    a.sync_log_to_remote(APP, V, stream(a))
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    real_write, in_write, release = stream_owner.atomic_write, threading.Event(), threading.Event()

    def slow_first_write(path, data):
        if not in_write.is_set():
            in_write.set()
            release.wait(10)  # P2 minted; its write lands late
        real_write(path, data)

    monkeypatch.setattr(stream_owner, "atomic_write", slow_first_write)
    owners = {}
    hosts = {"p2": cached_host(tmp_path, "b"), "p1": cached_host(tmp_path, "b")}

    def open_copy(name):
        owners[name] = stream(hosts[name])

    p2 = threading.Thread(target=open_copy, args=("p2",))
    p2.start()
    assert in_write.wait(10)
    p1 = threading.Thread(target=open_copy, args=("p1",))
    p1.start()
    time.sleep(0.3)  # P1 would mint and append now
    release.set()
    p1.join(10)
    p2.join(10)
    hosts["p1"].append_log_entry(APP, V, owners["p1"], tag(1, "k1"))
    hosts["p2"].append_log_entry(APP, V, owners["p2"], tag(2, "k2"))
    for h in (*hosts.values(), cached_host(tmp_path, "b")):
        h.sync_log_to_remote(APP, V, stream(h))

    assert owners["p1"] == owners["p2"]
    assert remote_tag_keys() == ["k0", "k1", "k2"]


def _mixed_ship(h, own):
    quietly(h.sync_log_to_remote, APP, V, own)
    quietly(h.sync_metrics_to_remote, APP, V, own)


def _mixed_turn(rng, tmp_path, step, roots, live, buf, keys, values):
    op, root = rng.random(), rng.choice(roots)
    if op < 0.08 and root in live:
        live.pop(root)  # its process ends
    elif op < 0.13:  # a fault-free ship, then prune --local-only
        h = cached_host(tmp_path, root)
        _ship(h, stream(h))
        live.pop(root, None)
        shutil.rmtree(tmp_path / root, ignore_errors=True)
    elif op < 0.17 and (tmp_path / root).exists():
        shutil.copytree(tmp_path / root, tmp_path / f"{root}{step}")
        roots.append(f"{root}{step}")
    elif op < 0.24:
        h = cached_host(tmp_path, root)
        if rng.random() < 0.5:
            flaky(h, rng, 0.4, METRIC_CALLS)
        if rng.random() < 0.5:
            quietly(compact_record, h, APP, V)
        else:
            quietly(lambda: compact_writer(h, APP, V, stream(h)))
    elif op < 0.30:
        if buf.append_log_entry(APP, V, stream(buf), tag(step, f"buf{step}")):
            keys.append(f"buf{step}")
        if buf.append_metric_block(APP, V, stream(buf), block(step * 10.0 + 9, start=step * 10 + 8)):
            values.append(step * 10.0 + 9)
    else:
        _mixed_append(rng, tmp_path, step, root, live, keys, values)


def _mixed_append(rng, tmp_path, step, root, live, keys, values):
    if root in live and rng.random() < 0.7:
        h = live[root]
    else:
        h = cached_host(tmp_path, root)
        if rng.random() < 0.5:
            flaky(h, rng, 0.4, LOG_CALLS + METRIC_CALLS)
        if rng.random() < 0.5:
            live[root] = h
    own = quietly(stream, h)
    if not own:
        return
    if quietly(h.append_log_entry, APP, V, own, tag(step, f"k{step}")):
        keys.append(f"k{step}")
    vals = [float(step * 10 + i) for i in range(rng.choice([1, 3]))]
    if quietly(h.append_metric_block, APP, V, own, block(*vals, start=step * 10)):
        values += vals
    if rng.random() < 0.6:
        _mixed_ship(h, own)


@pytest.mark.parametrize("seed", [*range(12), 19])  # 11: a stale read, 19: a stale ship state
def test_roots_copies_prunes_and_a_buffer_in_any_mix_converge(tmp_path, seed):
    rng = random.Random(seed)
    assert cached_host(tmp_path, "a").create_exclusive(APP, V, meta(V), {})
    roots, live, keys, values = ["a", "b", "c"], {}, [], []
    buf = BufferedRemoteStorage(s3_storage())
    for step in range(30):
        _mixed_turn(rng, tmp_path, step, roots, live, buf, keys, values)
    buf.close()
    alive = [r for r in roots if (tmp_path / r).exists()]
    for root in alive:
        h = cached_host(tmp_path, root)
        _ship(h, stream(h))

    assert remote_tag_keys() == sorted(keys)
    assert remote_metric_values() == sorted(values)
    for root in alive:
        h = cached_host(tmp_path, root)
        assert tag_keys(h.load_merged_log(APP, V)) == sorted(keys), root
        assert metric_values(h) == sorted(values), root
