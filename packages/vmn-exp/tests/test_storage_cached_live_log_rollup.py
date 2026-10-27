"""A live run ships a log segment per sync, and a remote reader GETs each one
(a run alive for 9 h on a 30 s sync interval: 1,100 objects per read). The
stream's owner rolls its own segments up while live — every
``LIVE_ROLLUP_SEGMENTS`` shipped, under its ship lock — so what a reader
lists stays bounded, and shipping goes on past the merged object."""
import pytest
from s3_helpers import cached_host, meta, mocked_bucket, raw_keys, s3_storage
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import buffered, cached_logs

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


def _remote_texts():
    logs = s3_storage().load_logs_by_writer(APP, V)
    return sorted((e["text"] for es in logs.values() for e in es), key=lambda t: int(t[1:]))


def _log_keys():
    return [k for k in raw_keys() if "/log/" in k]


def test_a_live_runs_segments_are_rolled_up_as_they_ship(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})

    stream = _ship(host, 0, 3 * ROLLUP + 3)

    objects = s3_storage().log_objects(APP, V, stream)
    assert len(objects) <= ROLLUP
    assert len(_log_keys()) == len(objects)  # nothing it merged is left behind
    assert _remote_texts() == [f"n{i}" for i in range(3 * ROLLUP + 3)]


def test_shipping_resumes_past_the_merged_object_in_a_new_process(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    _ship(host, 0, ROLLUP + 2)

    again = cached_host(tmp_path, "a")  # the ship state and the listing, read anew
    _ship(again, ROLLUP + 2, 2 * ROLLUP + 1)

    assert _remote_texts() == [f"n{i}" for i in range(2 * ROLLUP + 1)]


def test_a_finished_run_still_ends_as_one_object(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    stream = _ship(host, 0, ROLLUP + 3)

    host.save_file(APP, V, RUN_STATE_FILE, "state: finished\nexit_code: 0\n")
    host.sync_log_to_remote(APP, V, stream)

    assert len(s3_storage().log_objects(APP, V, stream)) == 1
    assert _remote_texts() == [f"n{i}" for i in range(ROLLUP + 3)]
