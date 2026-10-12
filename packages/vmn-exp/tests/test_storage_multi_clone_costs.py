"""What keeping several clones' writes exact costs a clone working alone:
nothing. A live run's ship is one PUT (and its journal entry), a one-shot
command on a run its own clone shipped downloads no log or metric object, and
neither lists the remote more often than the previous shared-stream shipping
did (the counts below are the S3 requests it made)."""
import pytest
from multi_clone_helpers import APP, V, block, one_host_bucket, stream, tag
from s3_helpers import cached_host, meta, op_counts, record_calls


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _requests(host):
    return record_calls(host._remote._s3)


def _at_most(calls, **limits):
    counts = dict(op_counts(calls))
    assert set(counts) <= set(limits), counts
    assert all(counts[op] <= limits[op] for op in counts), counts


def _ship_both(host, step):
    own = stream(host)
    assert host.append_log_entry(APP, V, own, tag(step, f"k{step}"))
    host.sync_log_to_remote(APP, V, own)
    assert host.append_metric_block(APP, V, own, block(float(step), start=step * 10))
    host.sync_metrics_to_remote(APP, V, own)


def _live_run(tmp_path):
    host = cached_host(tmp_path, "a")
    calls = _requests(host)
    assert host.create_exclusive(APP, V, meta(V), {})
    _ship_both(host, 0)
    return host, calls


def test_a_new_run_lists_its_log_and_metrics_once_each(tmp_path):
    _, calls = _live_run(tmp_path)

    _at_most(calls, HeadObject=1, PutObject=7, ListObjectsV2=2)


def test_a_live_runs_later_ships_only_upload(tmp_path):
    host, calls = _live_run(tmp_path)
    calls.clear()

    for step in range(1, 4):
        _ship_both(host, step)

    _at_most(calls, PutObject=12)


def test_a_tag_on_a_run_its_clone_shipped_downloads_nothing(tmp_path):
    _live_run(tmp_path)
    tagger = cached_host(tmp_path, "a")
    calls = _requests(tagger)

    own = stream(tagger)
    assert tagger.append_log_entry(APP, V, own, tag(10, "verdict"))
    tagger.sync_log_to_remote(APP, V, own)
    tagger.sync_metrics_to_remote(APP, V, own)

    _at_most(calls, GetObject=1, ListObjectsV2=3, PutObject=2)
    assert not [p for op, p in calls if op == "GetObject" and "/log/" in p["Key"]]


def test_adding_metrics_to_a_run_its_clone_shipped_downloads_nothing(tmp_path):
    _live_run(tmp_path)
    adder = cached_host(tmp_path, "a")
    calls = _requests(adder)

    own = stream(adder)
    assert adder.append_metric_block(APP, V, own, block(10.0, start=100))
    adder.sync_log_to_remote(APP, V, own)
    adder.sync_metrics_to_remote(APP, V, own)

    _at_most(calls, GetObject=1, ListObjectsV2=2, PutObject=2)


def test_a_fresh_clone_tagging_a_run_downloads_no_log(tmp_path):
    host, _ = _live_run(tmp_path)
    for step in range(1, 4):
        _ship_both(host, step)
    tagger = cached_host(tmp_path, "b")
    calls = _requests(tagger)

    own = stream(tagger)
    assert tagger.append_log_entry(APP, V, own, tag(10, "verdict"))
    tagger.sync_log_to_remote(APP, V, own)

    assert not [p for op, p in calls if op == "GetObject" and "/log/" in p["Key"]]


def test_a_fresh_clone_adding_metrics_downloads_no_other_clones_points(tmp_path):
    host, _ = _live_run(tmp_path)
    for step in range(1, 4):
        _ship_both(host, step)
    adder = cached_host(tmp_path, "b")
    calls = _requests(adder)

    own = stream(adder)
    assert adder.append_metric_block(APP, V, own, block(10.0, start=100))
    adder.sync_metrics_to_remote(APP, V, own)

    metric_gets = [p for op, p in calls if op == "GetObject" and "/metrics/" in p["Key"]]
    assert metric_gets == []
