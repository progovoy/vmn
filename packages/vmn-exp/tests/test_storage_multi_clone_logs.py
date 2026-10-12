"""Two clones of one repo on one host record under the same writer id (the
hostname) into the same run. However their commands interleave — a run living
in one clone while the other tags it, a ship whose network failed or whose
response was lost, a process that ended before it shipped, a cleared local
copy — the remote keeps every entry exactly once and each clone reads them
all: each clone appends to its own stream, which the remote replicates.
"""
import json
import threading

import pytest
from multi_clone_helpers import (
    APP,
    LOG_CALLS,
    V,
    lose_next_response,
    one_host_bucket,
    remote_tag_keys,
    stream,
    tag,
    view_tag_keys,
)
from s3_helpers import cached_host, meta, s3_storage


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _append(host, step, key, text="v"):
    assert host.append_log_entry(APP, V, stream(host), tag(step, key, text))


def _ship(host):
    host.sync_log_to_remote(APP, V, stream(host))


def _network_down(host):
    def fail(*args, **kwargs):
        raise RuntimeError("network down")

    for name in ("log_objects", "log_object_groups"):
        if hasattr(host._remote, name):
            setattr(host._remote, name, fail)


def _live_run(tmp_path, *keys):
    """Clone a's run, alive in this process, which shipped *keys*."""
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    for i, key in enumerate(keys):
        _append(a, i, key)
    _ship(a)
    return a


def test_a_line_as_long_as_the_remote_log_after_a_failed_ship_is_not_lost(tmp_path):
    a = _live_run(tmp_path, "ka")
    b = cached_host(tmp_path, "b")  # one command, the network down throughout
    _network_down(b)
    _append(b, 2, "kb")  # exactly as long as clone a's line
    with pytest.raises(RuntimeError):
        _ship(b)

    b = cached_host(tmp_path, "b")  # the next command, the network back
    _append(b, 3, "kc")
    _ship(b)

    assert remote_tag_keys() == ["ka", "kb", "kc"]
    assert view_tag_keys(b) == ["ka", "kb", "kc"]
    assert view_tag_keys(a) == ["ka", "kb", "kc"]


def test_a_tag_from_another_clone_survives_the_live_runs_next_ship(tmp_path):
    a = _live_run(tmp_path, "a0")
    _append(a, 1, "a1")  # logged, not shipped yet

    b = cached_host(tmp_path, "b")  # `vmn-exp tag` in the other clone
    _append(b, 2, "b-tag")
    _ship(b)
    _ship(a)  # the run's next heartbeat

    assert remote_tag_keys() == ["a0", "a1", "b-tag"]
    assert view_tag_keys(a) == ["a0", "a1", "b-tag"]
    assert view_tag_keys(cached_host(tmp_path, "b")) == ["a0", "a1", "b-tag"]


def test_a_tag_from_a_clone_that_read_the_log_before_the_runs_ship_is_kept(tmp_path):
    a = _live_run(tmp_path, "a0")
    b = cached_host(tmp_path, "b")
    _append(b, 2, "b1")

    _append(a, 1, "a1")  # as long as b's line
    _ship(a)
    _ship(b)

    assert remote_tag_keys() == ["a0", "a1", "b1"]
    assert view_tag_keys(b) == ["a0", "a1", "b1"]


def test_a_ship_whose_response_was_lost_is_not_shipped_twice(tmp_path):
    a = _live_run(tmp_path, "a0")
    _append(a, 1, "a1")
    lose_next_response(a, LOG_CALLS)
    with pytest.raises(RuntimeError):
        _ship(a)

    _append(a, 2, "a2")
    _ship(a)

    assert remote_tag_keys() == ["a0", "a1", "a2"]


def test_a_ship_whose_response_was_lost_before_the_command_ended_is_not_shipped_twice(
    tmp_path,
):
    _live_run(tmp_path, "a0")
    b = cached_host(tmp_path, "b")
    _append(b, 1, "b1")
    lose_next_response(b, LOG_CALLS)
    with pytest.raises(RuntimeError):
        _ship(b)

    later = cached_host(tmp_path, "b")
    _append(later, 2, "b2")
    _ship(later)

    assert remote_tag_keys() == ["a0", "b1", "b2"]


def _tag_line_of(size, step, key):
    """A tags entry whose JSONL line is *size* bytes long."""
    bare = len(json.dumps(tag(step, key, "")) + "\n")
    return tag(step, key, "z" * (size - bare))


def test_a_local_copy_dropped_and_regrown_to_the_shipped_size_keeps_its_line(tmp_path):
    _live_run(tmp_path, "a0")
    b = cached_host(tmp_path, "b")
    _append(b, 1, "b0")
    _ship(b)
    shipped = sum(size for _, size in s3_storage().log_objects(APP, V, stream(b)))

    b._local.delete(APP, V)  # the cache cleared (prune --local-only) while this lives
    assert b.append_log_entry(APP, V, stream(b), _tag_line_of(shipped, 2, "b1"))
    _ship(b)

    assert remote_tag_keys() == ["a0", "b0", "b1"]


def _ships_meet(*hosts):
    """Each host's next remote segment write waits until all of them got there."""
    barrier = threading.Barrier(len(hosts), timeout=5)
    for host in hosts:
        waited = []
        for name in ("save_file", "create_log_segment"):
            real = getattr(host._remote, name, None)
            if real is None:
                continue

            def call(*args, _real=real, _waited=waited, **kw):
                if not _waited:
                    _waited.append(True)
                    barrier.wait()
                return _real(*args, **kw)

            setattr(host._remote, name, call)


def _ship_together(*hosts):
    _ships_meet(*hosts)
    ships = [threading.Thread(target=_ship, args=(h,)) for h in hosts]
    for ship in ships:
        ship.start()
    for ship in ships:
        ship.join(10)


def test_two_clones_shipping_at_once_keep_both_lines(tmp_path):
    a = _live_run(tmp_path, "a0")
    b = cached_host(tmp_path, "b")
    _append(b, 1, "b1")
    _append(a, 2, "a1")

    _ship_together(a, b)

    assert remote_tag_keys() == ["a0", "a1", "b1"]


def test_two_processes_of_one_clone_shipping_at_once_keep_each_line_once(tmp_path):
    live = _live_run(tmp_path, "a0")
    tagger = cached_host(tmp_path, "a")  # `vmn-exp tag` beside the live run
    _append(live, 1, "a1")
    _append(tagger, 2, "a2")

    _ship_together(live, tagger)
    _append(live, 3, "a3")
    _ship(live)
    _ship(tagger)

    assert remote_tag_keys() == ["a0", "a1", "a2", "a3"]
    assert view_tag_keys(cached_host(tmp_path, "b")) == ["a0", "a1", "a2", "a3"]
