"""A local-first cache whose local copy of a writer's log is behind the
remote's (a fresh clone, a cleared cache, another clone on the same host —
all under one writer id) appends without losing the remote's entries.

Shipping resumes past the bytes the remote holds, which only works while the
local copy is a superset of the remote one; so before its first append under
a writer the cache brings its local copy up to the remote's, and shipping
merges rather than overwrites when the local copy shrank under it.
"""
import pytest
from s3_helpers import cached_host, meta, mocked_bucket, raw_keys, s3_storage
from vmn_exp.core import writer
from vmn_exp.core.logfiles import compacted_log_name
from vmn_exp.core.manage import tag_run
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log
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
    assert host.append_log_entry(APP, V, W, _note(text, second))


def _remote_texts():
    return [e["text"] for e in s3_storage().load_logs_by_writer(APP, V).get(W, [])]


def _log_keys():
    return [k for k in raw_keys() if "/log/" in k]


def _texts(storage):
    return [e["text"] for e in storage.load_merged_log(APP, V) if e["type"] == "note"]


def _host_a_wrote_three(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    for i in range(3):
        _append(host, f"a{i}", i)
    host.sync_log_to_remote(APP, V, W)
    return host


def test_a_fresh_root_appending_under_the_same_writer_keeps_the_remote_entries(tmp_path):
    a = _host_a_wrote_three(tmp_path)

    b = cached_host(tmp_path, "b")
    _append(b, "b0", 10)
    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "a2", "b0"]
    assert _texts(a) == ["a0", "a1", "a2", "b0"]
    assert _texts(b) == ["a0", "a1", "a2", "b0"]


def test_the_fresh_roots_local_copy_holds_the_remote_entries_once_it_appends(tmp_path):
    _host_a_wrote_three(tmp_path)

    b = cached_host(tmp_path, "b")
    _append(b, "b0", 10)

    local = b._local.load_logs_by_writer(APP, V)[W]
    assert [e["text"] for e in local] == ["a0", "a1", "a2", "b0"]


def test_remote_segments_survive_a_fresh_roots_append(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    for i in range(3):
        _append(a, f"a{i}", i)
        a.sync_log_to_remote(APP, V, W)  # the base object, then two segments
    assert len(s3_storage().log_objects(APP, V, W)) == 3

    b = cached_host(tmp_path, "b")
    _append(b, "b0", 10)
    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "a2", "b0"]


def test_a_compacted_remote_log_survives_a_fresh_roots_append(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    for i in range(3):
        _append(a, f"a{i}", i)
        a.sync_log_to_remote(APP, V, W)
    a.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    a.sync_log_to_remote(APP, V, W)  # the run finished: one merged object
    assert [n for n, _ in s3_storage().log_objects(APP, V, W)] == [
        compacted_log_name(W, 2)
    ]

    b = cached_host(tmp_path, "b")
    _append(b, "b0", 10)
    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "a2", "b0"]


def test_clones_taking_turns_under_one_writer_keep_every_entry(tmp_path):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    _append(a, "a0", 0)
    _append(a, "a1", 1)
    a.sync_log_to_remote(APP, V, W)

    b = cached_host(tmp_path, "b")
    _append(b, "b0", 10)
    b.sync_log_to_remote(APP, V, W)

    again = cached_host(tmp_path, "a")  # a later process in the first clone
    _append(again, "a2", 20)
    again.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "b0", "a2"]
    assert _texts(cached_host(tmp_path, "a")) == ["a0", "a1", "b0", "a2"]


def test_a_local_copy_dropped_under_a_live_cache_keeps_the_remote_entries(tmp_path):
    _host_a_wrote_three(tmp_path)
    b = cached_host(tmp_path, "b")
    _append(b, "b0", 10)
    b.sync_log_to_remote(APP, V, W)

    b._local.delete(APP, V)  # the cache cleared while this process lives
    _append(b, "b1", 11)
    b.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "a2", "b0", "b1"]


def test_a_buffered_pod_appending_after_its_run_finished_keeps_the_log(tmp_path):
    pod = open_storage(s3_uri("vmn-bucket", "exps"), area="runs", buffer_logs=True)
    assert pod.create_exclusive(APP, V, meta(V), {})
    for i in range(3):
        _append(pod, f"a{i}", i)
    pod.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    pod.sync_log_to_remote(APP, V, W)  # ships, compacts, drops the buffer

    _append(pod, "late", 10)
    pod.sync_log_to_remote(APP, V, W)

    assert _remote_texts() == ["a0", "a1", "a2", "late"]


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

    log = s3_storage().load_logs_by_writer(APP, V)[W]
    assert [e["type"] for e in log] == ["create", "note", "tags"]


def test_add_note_from_a_fresh_root_keeps_the_runs_log(tmp_path, same_writer):
    _run_logged_by_host_a(tmp_path)

    b = cached_host(tmp_path, "b")
    append_to_log(b, APP, V, create_log_entry("note", text="from b"))
    flush_log(b, APP, V)

    log = s3_storage().load_logs_by_writer(APP, V)[W]
    assert [e["type"] for e in log] == ["create", "note", "note"]
    assert [e["text"] for e in log if e["type"] == "note"] == ["from a", "from b"]


def test_an_up_to_date_local_copy_downloads_no_log(tmp_path):
    a = _host_a_wrote_three(tmp_path)
    logs_before = _log_keys()
    gets = []
    real = a._remote.load_file
    a._remote.load_file = lambda *args: gets.append(args[2]) or real(*args)

    _append(a, "a3", 3)
    a.sync_log_to_remote(APP, V, W)

    assert [g for g in gets if g.startswith("log/")] == []
    assert len(_log_keys()) == len(logs_before) + 1  # one new segment
    assert _remote_texts() == ["a0", "a1", "a2", "a3"]
