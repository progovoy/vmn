"""A local-first cache whose remote listing failed — here or in an earlier
process over the same root — or whose local copy was dropped and grew back
still keeps every remote entry: it ships its own stream, from what the
remote holds of it.
"""
import threading

import pytest
from s3_helpers import cached_host, meta
from test_storage_cached_log_seed import (  # noqa: F401
    APP,
    V,
    _append,
    _bucket,
    _fresh_host_appends,
    _remote_texts,
    _sync,
    _texts,
)

LONG = "x" * 300  # longer than the whole of host a's one-entry remote log


def _host_a_wrote_one(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    _append(a, "a0", 0)
    _sync(a)
    return a


def _remote_listing_fails_once(host):
    """*host*'s next listing of the remote log objects raises."""
    calls = []
    for name in ("log_objects", "log_object_groups"):
        real = getattr(host._remote, name)

        def flaky(*args, _real=real):
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError("transient")
            return _real(*args)

        setattr(host._remote, name, flaky)


def _host_whose_first_ship_failed(tmp_path, text):
    """A cache over a fresh root appended *text*; its ship's remote listing failed."""
    host = cached_host(tmp_path, "b")
    _remote_listing_fails_once(host)
    _append(host, text, 10)
    with pytest.raises(RuntimeError):
        _sync(host)
    return host


def test_a_failed_listing_keeps_the_remote_entries_when_the_new_line_outgrows_them(tmp_path):
    a = _host_a_wrote_one(tmp_path)
    b = _host_whose_first_ship_failed(tmp_path, LONG)

    _sync(b)

    assert _remote_texts() == ["a0", LONG]
    assert _texts(b) == ["a0", LONG]
    assert _texts(a) == ["a0", LONG]


def test_a_failed_listing_ships_a_new_line_exactly_as_long_as_the_remote_log(tmp_path):
    _host_a_wrote_one(tmp_path)
    b = _host_whose_first_ship_failed(tmp_path, "b0")  # as long as host a's "a0" line

    _sync(b)

    assert _remote_texts() == ["a0", "b0"]
    assert _texts(b) == ["a0", "b0"]


def test_a_ship_failed_in_an_earlier_process_keeps_the_remote_entries(tmp_path):
    _host_a_wrote_one(tmp_path)
    _host_whose_first_ship_failed(tmp_path, LONG)  # and that process ended unshipped

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
    _sync(b)

    assert _remote_texts() == ["a0", "b0", LONG]


def test_a_line_appended_while_a_ship_uploads_is_kept(tmp_path):
    _host_a_wrote_one(tmp_path)
    b = _host_whose_first_ship_failed(tmp_path, "b0")
    uploading, appended = threading.Event(), threading.Event()
    real_create = b._remote.create_log_segment

    def slow_create(*args):
        uploading.set()
        appended.wait(0.5)  # another thread's append lands now
        return real_create(*args)

    b._remote.create_log_segment = slow_create
    ship = threading.Thread(target=_sync, args=(b,))
    ship.start()
    assert uploading.wait(5)
    _append(b, "b1", 11)
    appended.set()
    ship.join()
    _sync(b)

    assert _remote_texts() == ["a0", "b0", "b1"]
