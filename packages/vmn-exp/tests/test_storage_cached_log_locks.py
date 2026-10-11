"""A local-first cache's log locks never hold up a SIGTERM finalizer.

The SDK finalizes on SIGTERM from a worker thread while the main thread sits
wherever the signal caught it, possibly holding a lock. So a first append's
seed takes no lock a ship holds across remote I/O, and neither an append nor a
merge waits long on the local-I/O-only lock a frozen append holds. Also: a local copy
holding only other log files of a writer (no ``log/<writer>.jsonl``) ships
without a TypeError.
"""
from frozen_holders import finishes_within, frozen_in, in_thread
from s3_helpers import cached_host, meta
from test_storage_cached_log_seed import (  # noqa: F401
    APP,
    V,
    W,
    _append,
    _bucket,
    _note,
    _remote_texts,
    _texts,
)
from vmn_exp.storage.cached_log_merge import LOCAL_LOCK_WAIT_SEC
from vmn_exp.storage.files import log_object_name

PROMPT_SEC = LOCAL_LOCK_WAIT_SEC + 3


def _host_a_wrote(tmp_path, *texts):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    for i, text in enumerate(texts):
        _append(a, text, i)
    a.sync_log_to_remote(APP, V, W)
    return a


def test_a_local_copy_without_the_writers_base_log_ships_without_a_type_error(tmp_path):
    _host_a_wrote(tmp_path, "a0", "a1", "a2")
    b = cached_host(tmp_path, "b")
    assert b.load_record(APP, V)[0] is not None
    segment = b"".join(b'{"timestamp": "2026-01-01T00:00:3%dZ", "type": "note", '
                       b'"text": "old segment %d"}\n' % (i, i) for i in range(3))
    b._local.save_file(APP, V, log_object_name(W, 1), segment)

    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "a2"]


def test_an_append_does_not_wait_on_a_thread_frozen_in_a_local_append(tmp_path):
    b = _host_a_wrote(tmp_path, "a0")
    entered, release = frozen_in(b._local, "append_log_entries")
    holder = in_thread(lambda: b.append_log_entry(APP, V, W, _note("frozen", 1)))
    assert entered.wait(5)

    finished, took = finishes_within(PROMPT_SEC, lambda: _append(b, "final", 2))
    release.set()
    holder.join(10)

    assert finished, f"the append waited {took:.1f}s on the frozen holder"
    assert "final" in _texts(b)


def test_a_first_append_does_not_wait_on_a_ship_stuck_in_remote_io(tmp_path):
    _host_a_wrote(tmp_path, "a0")
    b = cached_host(tmp_path, "b")
    b.append_log_entry(APP, V, "other", _note("o0", 1))
    entered, release = frozen_in(b._remote, "log_objects")
    shipper = in_thread(lambda: b.sync_log_to_remote(APP, V, "other"))
    assert entered.wait(5)

    finished, took = finishes_within(PROMPT_SEC, lambda: _append(b, "b0", 2))
    release.set()
    shipper.join(10)
    b.sync_log_to_remote(APP, V, W)

    assert finished, f"the first append waited {took:.1f}s on the stuck ship"
    assert _remote_texts() == ["a0", "b0"]


def test_a_merge_gives_up_on_a_frozen_append_and_merges_on_the_next_ship(tmp_path):
    _host_a_wrote(tmp_path, "a0", "a1")
    b = cached_host(tmp_path, "b")
    real_list = b._remote.log_objects
    failed = []

    def fails_once(*args):  # the seed fails: the next ship must merge
        if not failed:
            failed.append(args)
            raise RuntimeError("transient")
        return real_list(*args)

    b._remote.log_objects = fails_once
    _append(b, "b0", 3)
    entered, release = frozen_in(b._local, "append_log_entries")
    holder = in_thread(lambda: b.append_log_entry(APP, V, W, _note("frozen", 4)))
    assert entered.wait(5)

    finished, took = finishes_within(PROMPT_SEC, lambda: _ship_quietly(b))
    release.set()
    holder.join(10)
    b.sync_log_to_remote(APP, V, W)

    assert finished, f"the ship waited {took:.1f}s on the frozen append"
    assert _remote_texts() == ["a0", "a1", "b0", "frozen"]


def _ship_quietly(host):
    try:
        host.sync_log_to_remote(APP, V, W)
    except Exception:
        pass  # a sync is best effort: the next one retries
