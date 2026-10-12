"""A local-first cache whose local copy of a run has less of a writer's log
than the remote (a fresh clone, a cleared cache, another clone on the same
host — all under one writer id) appends without losing the remote's entries:
each copy appends to a stream of its own (``<writer>~<owner>``), which only
its own file ever ships to.
"""
import pytest
from s3_helpers import cached_host, meta, mocked_bucket, raw_keys, s3_storage
from vmn_exp.core import writer
from vmn_exp.core.logfiles import compacted_log_name
from vmn_exp.core.manage import tag_run
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.streams import display_writer
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log, own_stream
from vmn_exp.storage import buffered
from vmn_exp.storage.open import open_storage
from vmn_exp.storage.uri import s3_uri

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
W = "w"
FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


def _note(text, second):
    return {"timestamp": f"2026-01-01T00:00:{second:02d}Z", "type": "note", "text": text}


def _append(host, text, second):
    assert host.append_log_entry(APP, V, own_stream(host, APP, V), _note(text, second))


def _sync(host):
    host.sync_log_to_remote(APP, V, own_stream(host, APP, V))


def _remote_log(writer_id=None):
    """The entries of every remote stream of *writer_id* (any), by time."""
    logs = s3_storage().load_logs_by_writer(APP, V)
    entries = [e for stream, es in logs.items() for e in es
               if writer_id is None or display_writer(stream) == writer_id]
    return sorted(entries, key=lambda e: e["timestamp"])


def _remote_texts():
    return [e["text"] for e in _remote_log()]


def _log_keys():
    return [k for k in raw_keys() if "/log/" in k]


def _texts(storage):
    return [e["text"] for e in storage.load_merged_log(APP, V) if e["type"] == "note"]


def _host_a_wrote_three(tmp_path, sync_each=False):
    """Host a's run logged a0..a2 under W: one shipped object, or (with
    *sync_each*) the base object and two segments."""
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    for i in range(3):
        _append(host, f"a{i}", i)
        if sync_each:
            _sync(host)
    _sync(host)
    return host


def _fresh_host_appends(tmp_path, text="b0", name="b"):
    """A cache over the fresh root *name* appends *text* under W and syncs."""
    host = cached_host(tmp_path, name)
    _append(host, text, 10)
    _sync(host)
    return host


def test_a_fresh_root_appending_under_the_same_writer_keeps_the_remote_entries(tmp_path):
    a = _host_a_wrote_three(tmp_path)

    b = _fresh_host_appends(tmp_path)

    assert _remote_texts() == ["a0", "a1", "a2", "b0"]
    assert _texts(a) == ["a0", "a1", "a2", "b0"]
    assert _texts(b) == ["a0", "a1", "a2", "b0"]


def test_remote_segments_survive_a_fresh_roots_append(tmp_path):
    a = _host_a_wrote_three(tmp_path, sync_each=True)
    assert len(s3_storage().log_objects(APP, V, own_stream(a, APP, V))) == 3

    _fresh_host_appends(tmp_path)

    assert _remote_texts() == ["a0", "a1", "a2", "b0"]


def test_a_compacted_remote_log_survives_a_fresh_roots_append(tmp_path):
    a = _host_a_wrote_three(tmp_path, sync_each=True)
    a.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    _sync(a)  # the run finished: one merged object
    stream = own_stream(a, APP, V)
    assert [n for n, _ in s3_storage().log_objects(APP, V, stream)] == [
        compacted_log_name(stream, 2)
    ]

    _fresh_host_appends(tmp_path)

    assert _remote_texts() == ["a0", "a1", "a2", "b0"]


def test_clones_taking_turns_under_one_writer_keep_every_entry(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    _append(a, "a0", 0)
    _append(a, "a1", 1)
    _sync(a)

    _fresh_host_appends(tmp_path)

    again = cached_host(tmp_path, "a")  # a later process in the first clone
    _append(again, "a2", 20)
    _sync(again)

    assert _remote_texts() == ["a0", "a1", "b0", "a2"]
    assert _texts(cached_host(tmp_path, "a")) == ["a0", "a1", "b0", "a2"]


def test_a_local_copy_dropped_under_a_live_cache_keeps_the_remote_entries(tmp_path):
    _host_a_wrote_three(tmp_path)
    b = _fresh_host_appends(tmp_path)

    b._local.delete(APP, V)  # the cache cleared while this process lives
    _append(b, "b1", 11)
    _sync(b)

    assert _remote_texts() == ["a0", "a1", "a2", "b0", "b1"]


def _finished_buffered_pod(lines):
    """A direct-to-S3 pod whose run logged *lines* and finished: shipped,
    compacted, its buffer dropped."""
    pod = open_storage(s3_uri("vmn-bucket", "exps"), area="runs", buffer_logs=True)
    assert pod.create_exclusive(APP, V, meta(V), {})
    for i, text in enumerate(lines):
        _append(pod, text, i)
    pod.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    _sync(pod)
    return pod


def test_a_buffered_pod_appending_after_its_run_finished_keeps_the_log():
    pod = _finished_buffered_pod(["a0", "a1", "a2"])

    _append(pod, "late", 10)
    _sync(pod)

    assert _remote_texts() == ["a0", "a1", "a2", "late"]


def test_a_buffered_pod_ships_a_long_line_appended_after_its_run_finished():
    pod = _finished_buffered_pod(["a0"])

    _append(pod, "x" * 200, 10)  # longer than everything the pod had shipped
    _sync(pod)

    assert _remote_texts() == ["a0", "x" * 200]


@pytest.fixture
def same_writer(monkeypatch):
    """Every host below records under writer id W (the CLI's get_writer_id)."""
    monkeypatch.setenv("VMN_WRITER_ID", W)
    monkeypatch.setattr(writer, "_WRITER_ID", None)


def _run_logged_by_host_a(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    append_to_log(a, APP, V, create_log_entry("create", note=None))
    append_to_log(a, APP, V, create_log_entry("note", text="from a"))
    flush_log(a, APP, V)


def test_tag_from_a_fresh_root_keeps_the_runs_log(tmp_path, same_writer):
    _run_logged_by_host_a(tmp_path)

    assert tag_run(cached_host(tmp_path, "b"), APP, V, tags={"verdict": "keep"})

    log = _remote_log(W)
    assert [e["type"] for e in log] == ["create", "note", "tags"]


def test_add_note_from_a_fresh_root_keeps_the_runs_log(tmp_path, same_writer):
    _run_logged_by_host_a(tmp_path)

    b = cached_host(tmp_path, "b")
    append_to_log(b, APP, V, create_log_entry("note", text="from b"))
    flush_log(b, APP, V)

    log = _remote_log(W)
    assert [e["type"] for e in log] == ["create", "note", "note"]
    assert [e["text"] for e in log if e["type"] == "note"] == ["from a", "from b"]


def test_an_up_to_date_local_copy_downloads_no_log(tmp_path):
    a = _host_a_wrote_three(tmp_path)
    logs_before = _log_keys()
    gets = []
    real = a._remote.load_file
    a._remote.load_file = lambda *args: gets.append(args[2]) or real(*args)

    _append(a, "a3", 3)
    _sync(a)

    assert [g for g in gets if g.startswith("log/")] == []
    assert len(_log_keys()) == len(logs_before) + 1  # one new segment
    assert _remote_texts() == ["a0", "a1", "a2", "a3"]
