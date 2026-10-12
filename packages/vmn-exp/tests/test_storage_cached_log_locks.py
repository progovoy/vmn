"""A local-first cache's locks never hold up an append or a SIGTERM finalizer.

The SDK finalizes on SIGTERM from a worker thread while the main thread sits
wherever the signal caught it, possibly holding a lock. Appends take no lock
at all, so they never wait on a ship stuck in remote I/O nor on a frozen
append; a ship waits on the record copy's ship lock, which a frozen thread
may hold, at most ``FINALIZING_WAIT_SEC`` while finalizing. Also: a local
copy holding only other log files of a stream (no ``log/<stream>.jsonl``)
ships without a TypeError.
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
    _sync,
    _texts,
)
from vmn_exp.core.writer import own_stream
from vmn_exp.storage.files import log_object_name
from vmn_exp.storage.ship_state import FINALIZING_WAIT_SEC

PROMPT_SEC = FINALIZING_WAIT_SEC + 3


def _host_a_wrote(tmp_path, *texts):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    for i, text in enumerate(texts):
        _append(a, text, i)
    _sync(a)
    return a


def test_a_local_copy_without_the_writers_base_log_ships_without_a_type_error(tmp_path):
    _host_a_wrote(tmp_path, "a0", "a1", "a2")
    b = cached_host(tmp_path, "b")
    assert b.load_record(APP, V)[0] is not None
    segment = b"".join(b'{"timestamp": "2026-01-01T00:00:3%dZ", "type": "note", '
                       b'"text": "old segment %d"}\n' % (i, i) for i in range(3))
    b._local.save_file(APP, V, log_object_name(own_stream(b, APP, V), 1), segment)

    _sync(b)

    assert _remote_texts() == ["a0", "a1", "a2"]


def test_an_append_does_not_wait_on_a_thread_frozen_in_a_local_append(tmp_path):
    b = _host_a_wrote(tmp_path, "a0")
    entered, release = frozen_in(b._local, "append_log_entries")
    holder = in_thread(lambda: _append(b, "frozen", 1))
    assert entered.wait(5)

    finished, took = finishes_within(PROMPT_SEC, lambda: _append(b, "final", 2))
    release.set()
    holder.join(10)

    assert finished, f"the append waited {took:.1f}s on the frozen holder"
    assert "final" in _texts(b)


def test_an_append_does_not_wait_on_a_ship_stuck_in_remote_io(tmp_path):
    _host_a_wrote(tmp_path, "a0")
    b = cached_host(tmp_path, "b")
    _append(b, "b0", 1)
    entered, release = frozen_in(b._remote, "log_object_groups")
    shipper = in_thread(lambda: _sync(b))
    assert entered.wait(5)

    finished, took = finishes_within(PROMPT_SEC, lambda: _append(b, "b1", 2))
    release.set()
    shipper.join(10)
    _sync(b)

    assert finished, f"the append waited {took:.1f}s on the stuck ship"
    assert _remote_texts() == ["a0", "b0", "b1"]


def test_a_ship_does_not_wait_on_a_frozen_append(tmp_path):
    _host_a_wrote(tmp_path, "a0", "a1")
    b = cached_host(tmp_path, "b")
    _append(b, "b0", 3)
    entered, release = frozen_in(b._local, "append_log_entries")
    holder = in_thread(lambda: _append(b, "frozen", 4))
    assert entered.wait(5)

    finished, took = finishes_within(PROMPT_SEC, lambda: _sync(b))
    release.set()
    holder.join(10)
    _sync(b)

    assert finished, f"the ship waited {took:.1f}s on the frozen append"
    assert _remote_texts() == ["a0", "a1", "b0", "frozen"]


def test_a_ship_while_finalizing_gives_up_on_a_frozen_ship_lock_holder(tmp_path):
    from vmn_exp.storage import ship_state

    b = _host_a_wrote(tmp_path, "a0")
    _append(b, "a1", 1)
    record = b._local.local_record_dir(APP, V)
    held, release = in_thread_holding(ship_state.ship_lock(record))

    with ship_state.finalizing():
        finished, took = finishes_within(PROMPT_SEC, lambda: _ship_quietly(b))
    release.set()
    held.join(10)
    _sync(b)

    assert finished, f"the finalizing ship waited {took:.1f}s on the frozen holder"
    assert _remote_texts() == ["a0", "a1"]


def in_thread_holding(lock):
    """A thread that holds *lock* (a context manager) until *release* is set."""
    import threading

    entered, release = threading.Event(), threading.Event()

    def hold():
        with lock:
            entered.set()
            release.wait(60)

    thread = in_thread(hold)
    assert entered.wait(5)
    return thread, release


def _ship_quietly(host):
    try:
        _sync(host)
    except Exception:
        pass  # a sync is best effort: the next one retries
