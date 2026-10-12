"""The experiment index folds a log incrementally only while its bytes grow at
the end. A local log rewritten into a bigger file, or a reader switching from
the remote copy of a stream's log to a local copy that is not a superset of
it, is folded again, so the index (and its persisted cache) always equals a
full read of the same storage — however the clones' streams interleave.
"""
import json
import os
import time

import pytest
from s3_helpers import cached_host, entry, meta, mocked_bucket, s3_storage
from test_storage_cached_log_seed import _note
from test_storage_cached_log_seed_failed import _remote_listing_fails_once
from vmn_exp.core import index as experiment_index
from vmn_exp.core import writer
from vmn_exp.core.index import ExperimentIndex, direct_rows, direct_snapshot
from vmn_exp.core.intent import build_intent_entry
from vmn_exp.core.manage import tag_run
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log, own_stream
from vmn_exp.storage import buffered

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
W = "w"
LOG = "log/w.jsonl"
LONG = "x" * 400  # one line longer than the whole remote log


@pytest.fixture
def bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


def _line(e):
    return json.dumps(e) + "\n"


def _remote_offline_for(host, n):
    """*host*'s next *n* remote log listings and saves raise."""
    left = {"n": n}
    for name in ("log_objects", "log_object_groups", "save_file", "create_log_segment"):
        real = getattr(host._remote, name)

        def flaky(*args, _real=real, **kw):
            if left["n"] > 0:
                left["n"] -= 1
                raise RuntimeError("network down")
            return _real(*args, **kw)

        setattr(host._remote, name, flaky)


def _host_a_shipped(tmp_path, *entries):
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    for e in entries:
        assert a.append_log_entry(APP, V, own_stream(a, APP, V), e)
    a.sync_log_to_remote(APP, V, own_stream(a, APP, V))
    return a


# -- a local-first cache's local copy --------------------------------------------


def _settle(host):
    """The record's folders an hour old: its next listings re-stat its files."""
    record = host._local.plain_record_dir(APP, V)
    old = time.time_ns() - 3600 * 10**9
    for path in (os.path.join(record, "log"), record):
        os.utime(path, ns=(old, old))


def test_an_append_keeps_a_local_log_files_identity_and_a_replace_changes_it(
    tmp_path, bucket
):
    from vmn_exp.core.logfiles import append_identity

    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    host.append_log_entry(APP, V, W, entry(1))
    _settle(host)
    first = host.list_files(APP)[V][LOG]

    host.append_log_entry(APP, V, W, entry(2))
    appended = host.list_files(APP)[V][LOG]  # re-stat-ed, not scanned
    host._local.save_file(APP, V, LOG, _line(entry(0)) + _line(entry(1)) + _line(entry(2)))
    replaced = host.list_files(APP)[V][LOG]

    assert append_identity(first) is not None
    assert append_identity(appended) == append_identity(first)
    assert append_identity(replaced) != append_identity(appended)
    assert host.list_files(APP, keys=[V])[V][LOG] == replaced


def _params(second, **params):
    return {"timestamp": f"2026-01-01T00:00:{second:02d}Z", "type": "params",
            "params": params}


def test_a_local_log_replaced_by_a_bigger_one_is_folded_again(tmp_path, bucket):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    host.append_log_entry(APP, V, W, _params(1, lr=0.1))
    index = ExperimentIndex(host, APP, cache_path=str(tmp_path / "idx.sqlite"))
    index.refresh()

    other = _params(0, layers=4, opt="adam" * 10)
    host._local.save_file(APP, V, LOG, _line(other) + _line(_params(1, lr=0.1)))

    assert index.refresh().rows() == direct_rows(host, APP)[0]
    assert index.rows()[0]["params"] == {"layers": 4, "opt": "adam" * 10, "lr": 0.1}


# -- a local-first cache merging the remote's lines in --------------------------


def test_an_index_over_a_cache_whose_ship_failed_matches_a_full_read_after_the_next(
    tmp_path, bucket
):
    _host_a_shipped(tmp_path, entry(1))
    b = cached_host(tmp_path, "b")
    _remote_listing_fails_once(b)
    assert b.append_log_entry(APP, V, own_stream(b, APP, V), _note(LONG, 10))  # local copy: LONG only
    index = ExperimentIndex(b, APP).refresh()
    with pytest.raises(RuntimeError):
        b.sync_log_to_remote(APP, V, own_stream(b, APP, V))  # its listing fails

    b.sync_log_to_remote(APP, V, own_stream(b, APP, V))

    remote = sorted((e for es in s3_storage().load_logs_by_writer(APP, V).values() for e in es),
                    key=lambda e: e["timestamp"])
    assert [e["type"] for e in remote] == [
        "metrics",
        "note",
    ]
    rows = index.refresh().rows()
    assert rows == direct_rows(b, APP)[0]
    assert rows == ExperimentIndex(b, APP).refresh().rows()
    assert rows[0]["metrics"] == {"i": 1}


def test_a_persisted_index_refolds_a_log_another_process_merged(tmp_path, bucket):
    _host_a_shipped(tmp_path, _params(1, lr=0.1))
    died = cached_host(tmp_path, "b")  # its seed failed; it appended, never shipped
    _remote_listing_fails_once(died)
    assert died.append_log_entry(APP, V, own_stream(died, APP, V), _note(LONG, 10))
    cache = str(tmp_path / "idx.sqlite")
    ExperimentIndex(cached_host(tmp_path, "b"), APP, cache_path=cache).refresh()

    later = cached_host(tmp_path, "b")  # a one-shot append + flush merges
    assert later.append_log_entry(APP, V, own_stream(later, APP, V), _note("b1", 11))
    later.sync_log_to_remote(APP, V, own_stream(later, APP, V))

    reader = cached_host(tmp_path, "b")
    rows = ExperimentIndex(reader, APP, cache_path=cache).refresh().rows()
    assert rows == direct_rows(reader, APP)[0]
    assert rows[0]["params"] == {"lr": 0.1}


def _view(snap):
    row = snap.rows[0]
    return {
        "intent": snap.intent_of(V),
        "features": snap.features_of(V),
        "row": {k: row.get(k) for k in ("author", "has_intent", "params")},
    }


def test_an_index_that_read_the_remote_copy_refolds_when_the_local_copy_outgrows_it(
    tmp_path, bucket
):
    features = {
        "timestamp": "2026-01-01T00:00:00Z", "type": "features", "features_version": 1,
        "source": "capture", "author": {"git_user_email": "alice@x.io"},
        "changed": {"files": ["train.py"]},
    }
    _host_a_shipped(
        tmp_path,
        {"timestamp": "2026-01-01T00:00:00Z", "type": "create", "params": {"lr": 0.1}},
        features,
        _note("a0", 1),
    )
    b = cached_host(tmp_path, "b")
    cache = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(b, APP, cache_path=cache)
    index.refresh()  # b has no local log yet: the remote copy

    _remote_listing_fails_once(b)
    intent = {"timestamp": "2026-01-01T00:00:10Z", "type": "intent",
              "text": "try focal loss " + "x" * 400}
    assert b.append_log_entry(APP, V, own_stream(b, APP, V), intent)  # the local copy: just the intent
    assert _view(index.refresh().snapshot()) == _view(direct_snapshot(b, APP))
    with pytest.raises(RuntimeError):
        b.sync_log_to_remote(APP, V, own_stream(b, APP, V))  # its listing fails

    b.sync_log_to_remote(APP, V, own_stream(b, APP, V))
    want = _view(direct_snapshot(b, APP))
    assert want["intent"] is not None and want["features"] is not None
    assert _view(index.refresh().snapshot()) == want
    later = ExperimentIndex(cached_host(tmp_path, "b"), APP, cache_path=cache)
    assert _view(later.refresh().snapshot()) == want


def test_list_after_a_flaky_add_and_a_merging_tag_shows_every_entry(
    tmp_path, bucket, monkeypatch
):
    monkeypatch.setenv("VMN_WRITER_ID", "h")  # two clones, one host
    writer._WRITER_ID = None
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    append_to_log(a, APP, V, create_log_entry("create", params={"lr": 0.1, "layers": 4}))
    flush_log(a, APP, V)

    b = cached_host(tmp_path, "b")  # `vmn-exp add --intent`, network down
    _remote_offline_for(b, 2)
    append_to_log(b, APP, V, dict(build_intent_entry("why: " + "y" * 600, ["k"]),
                                  timestamp="2026-01-01T00:00:05Z"))
    with pytest.raises(RuntimeError):
        flush_log(b, APP, V)

    def listed():
        return experiment_index.indexed_snapshot(cached_host(tmp_path, "b"), APP,
                                                 wait=True).rows

    listed()  # `vmn-exp list`
    assert tag_run(cached_host(tmp_path, "b"), APP, V, {"k": "v"})  # network back

    rows, truth = listed(), direct_rows(cached_host(tmp_path, "b"), APP)[0]
    assert rows[0]["params"] == truth[0]["params"] == {"lr": 0.1, "layers": 4}
    assert rows[0]["tags"] == truth[0]["tags"] == {"k": "v"}
    assert rows[0]["has_intent"] is truth[0]["has_intent"] is True
