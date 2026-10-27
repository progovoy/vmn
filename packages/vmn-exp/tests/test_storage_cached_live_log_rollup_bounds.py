"""A live rollup rewrites the whole stream under its ship lock, which the
SDK's SIGTERM finalizer waits on for 2 s only: it runs on periodic syncs
alone, never in a finalizer or an exit flush, and only while what it merges
is small (``LIVE_ROLLUP_MAX_BYTES``) — past that the server's incremental
reads keep repeat views cheap."""
import pytest
from s3_helpers import cached_host, meta, mocked_bucket, s3_storage
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import buffered, cached_logs
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.ship_state import finalizing

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
ROLLUP = 8


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    monkeypatch.setattr(cached_logs, "LIVE_ROLLUP_SEGMENTS", ROLLUP)
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


def _note(i):
    return {"timestamp": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z", "type": "note", "text": f"n{i}"}


def _ship(host, start, stop):
    stream = own_stream(host, APP, V)
    for i in range(start, stop):
        assert host.append_log_entry(APP, V, stream, _note(i))
        host.sync_log_to_remote(APP, V, stream)
    return stream


def _objects(stream):
    return s3_storage().log_objects(APP, V, stream)


def test_a_stream_past_the_byte_cap_is_not_rolled_up(tmp_path, monkeypatch):
    monkeypatch.setattr(cached_logs, "LIVE_ROLLUP_MAX_BYTES", 200)  # ~3 notes
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})

    stream = _ship(host, 0, ROLLUP + 2)

    assert len(_objects(stream)) == ROLLUP + 2


def test_a_finalizer_ship_never_rolls_up(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    stream = _ship(host, 0, ROLLUP)

    with finalizing():
        _ship(host, ROLLUP, ROLLUP + 1)  # the segment a periodic sync rolls up at

    assert len(_objects(stream)) == ROLLUP + 1


def test_an_exit_flush_never_rolls_up():
    pod = BufferedRemoteStorage(s3_storage(), area="runs", flush_interval_sec=0)
    pod.save(APP, V, meta(V), {})
    stream = own_stream(pod, APP, V)
    for i in range(ROLLUP):
        assert pod.append_log_entry(APP, V, stream, _note(i))
    pod._flush_interval_sec = 3600  # the next lines wait for the exit flush
    assert pod.append_log_entry(APP, V, stream, _note(ROLLUP))

    pod.close()

    assert len(_objects(stream)) == ROLLUP + 1
