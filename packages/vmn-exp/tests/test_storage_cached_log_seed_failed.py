"""A local-first cache that could not bring its local copy of a writer's log
up to the remote's — its seed failed, here or in an earlier process over the
same root, or the local copy was dropped and grew back — still keeps every
remote entry: shipping merges the remote's lines in rather than shipping from
an offset the local copy does not line up with.
"""
import threading

from s3_helpers import cached_host, meta
from test_storage_cached_log_seed import (  # noqa: F401
    APP,
    V,
    W,
    _append,
    _bucket,
    _fresh_host_appends,
    _remote_texts,
    _texts,
)

LONG = "x" * 300  # longer than the whole of host a's one-entry remote log


def _host_a_wrote_one(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    _append(a, "a0", 0)
    a.sync_log_to_remote(APP, V, W)
    return a


def _remote_listing_fails_once(host):
    """*host*'s next listing of a writer's remote log objects raises."""
    real = host._remote.log_objects
    calls = []

    def flaky(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return real(*args)

    host._remote.log_objects = flaky


def _host_whose_seed_failed(tmp_path, text):
    host = cached_host(tmp_path, "b")
    _remote_listing_fails_once(host)
    _append(host, text, 10)
    return host


def test_a_failed_seed_keeps_the_remote_entries_when_the_new_line_outgrows_them(tmp_path):
    a = _host_a_wrote_one(tmp_path)
    b = _host_whose_seed_failed(tmp_path, LONG)

    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", LONG]
    assert _texts(b) == ["a0", LONG]
    assert _texts(a) == ["a0", LONG]


def test_a_failed_seed_ships_a_new_line_exactly_as_long_as_the_remote_log(tmp_path):
    _host_a_wrote_one(tmp_path)
    b = _host_whose_seed_failed(tmp_path, "b0")  # as long as host a's "a0" line

    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "b0"]
    assert _texts(b) == ["a0", "b0"]


def test_a_seed_failed_in_an_earlier_process_keeps_the_remote_entries(tmp_path):
    _host_a_wrote_one(tmp_path)
    _host_whose_seed_failed(tmp_path, LONG)  # and that process ended unshipped

    later = _fresh_host_appends(tmp_path, text="b1")

    assert _remote_texts() == ["a0", LONG, "b1"]
    assert _texts(later) == ["a0", LONG, "b1"]


def test_a_local_copy_dropped_and_regrown_past_the_shipped_bytes_keeps_the_remote_entries(
    tmp_path,
):
    _host_a_wrote_one(tmp_path)
    b = _fresh_host_appends(tmp_path)

    b._local.delete(APP, V)  # the cache cleared while this process lives
    _append(b, LONG, 11)
    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "b0", LONG]


def test_a_line_appended_while_a_ship_merges_the_remote_lines_is_kept(tmp_path):
    _host_a_wrote_one(tmp_path)
    b = _host_whose_seed_failed(tmp_path, "b0")
    rewriting, appended = threading.Event(), threading.Event()
    real_save = b._local.save_file

    def slow_save(*args):
        rewriting.set()
        appended.wait(0.5)  # another thread's append lands now, unless it waits
        return real_save(*args)

    b._local.save_file = slow_save
    ship = threading.Thread(target=b.sync_log_to_remote, args=(APP, V, W))
    ship.start()
    assert rewriting.wait(5)
    _append(b, "b1", 11)
    appended.set()
    ship.join()
    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "b0", "b1"]
