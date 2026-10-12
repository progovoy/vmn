"""A ``cp -r`` copy of a root holds a stale prefix of the original's streams:
it reads their metrics from the remote, compacts them from the remote's
objects and never ships them (the original alone ships its metric streams);
log lines it ships for the original are a prefix and land once. Report
header edits from two clones of one host land in two streams."""
import shutil
from collections import Counter

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    remote_metric_values,
    stream,
    tag,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.metric_compact import compact_record, compact_writer, seal_writer
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.streams import new_owner, stream_key
from vmn_exp.reports import log as report_log
from vmn_exp.reports import store as report_store

FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _add(host, value):
    own = stream(host)
    assert host.append_metric_block(APP, V, own, block(value, start=int(value)))
    return own


def _copied_then_shipped_more(tmp_path):
    """Root a ships 1.0, is copied to a2, then ships 2.0."""
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = _add(a, 1.0)
    a.sync_metrics_to_remote(APP, V, own)
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    _add(a, 2.0)
    a.sync_metrics_to_remote(APP, V, own)
    assert remote_metric_values() == [1.0, 2.0]
    return cached_host(tmp_path, "a2")


def test_a_copy_reads_the_points_the_original_shipped_after_the_copy(tmp_path):
    copy = _copied_then_shipped_more(tmp_path)

    assert metric_values(copy) == [1.0, 2.0]


def test_compacting_in_a_copy_keeps_the_points_the_original_shipped_after_the_copy(tmp_path):
    copy = _copied_then_shipped_more(tmp_path)

    compact_record(copy, APP, V)

    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(copy) == [1.0, 2.0]


def test_a_copy_ships_nothing_over_a_stream_the_original_sealed_since(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = _add(a, 1.0)
    a.sync_metrics_to_remote(APP, V, own)
    _add(a, 2.0)  # not shipped yet when the root is copied
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    assert seal_writer(a, APP, V, own)

    cached_host(tmp_path, "a2").sync_metrics_to_remote(APP, V, own)

    assert remote_metric_values() == [1.0, 2.0]


def _failing_put_indexed(host):
    def fail(*args, **kw):
        raise RuntimeError("network blip")

    host._remote.put_indexed = fail


def test_the_original_restores_points_a_copy_compacted_away_after_its_own_compaction_failed(
        tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = _add(a, 1.0)
    a.sync_metrics_to_remote(APP, V, own)
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    _add(a, 2.0)
    _failing_put_indexed(a)
    with pytest.raises(RuntimeError):
        compact_writer(a, APP, V, own)
    compact_record(cached_host(tmp_path, "a2"), APP, V)  # from the remote: 1.0 only

    cached_host(tmp_path, "a").sync_metrics_to_remote(APP, V, own)

    assert remote_metric_values() == [1.0, 2.0]


def test_blocks_appended_under_a_one_off_owner_are_shipped(tmp_path):
    assert cached_host(tmp_path, "a").create_exclusive(APP, V, meta(V), {})
    b = cached_host(tmp_path, "b")
    one_off = stream_key("h", new_owner())  # named while b's record fetch failed

    assert b.append_metric_block(APP, V, one_off, block(1.0))
    b.sync_metrics_to_remote(APP, V, one_off)

    assert remote_metric_values() == [1.0]


def _remote_tag_counts():
    logs = s3_storage().load_logs_by_writer(APP, V)
    return Counter(k for entries in logs.values() for e in entries
                   if e.get("type") == "tags" for k in e["set"])


def test_log_lines_a_copy_ships_for_the_original_land_once_after_it_compacts_them(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.sync_log_to_remote(APP, V, own)
    a.append_log_entry(APP, V, own, tag(2, "k2"))  # not shipped yet when copied
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    copy = cached_host(tmp_path, "a2")
    copy.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    copy.sync_log_to_remote(APP, V, stream(copy))  # ships, then compacts at run end

    a.sync_log_to_remote(APP, V, own)

    assert _remote_tag_counts() == {"k1": 1, "k2": 1}


def test_report_header_edits_from_two_clones_are_all_kept(tmp_path):
    a = cached_host(tmp_path, "a")
    rid = report_store.create(a, "t-a1", "body")
    b = cached_host(tmp_path, "b")
    report_log.set_pinned(b, rid, True)
    report_log.set_title(a, rid, "t-a2-longer-title")
    report_log.set_archived(b, rid, True)

    entries = report_log.read_header_entries(cached_host(tmp_path, "c"), rid)

    assert sorted(e["type"] for e in entries) == ["archived", "pinned", "title", "title"]


def test_lines_the_original_appends_after_a_copy_compacted_its_log_reach_the_remote(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.sync_log_to_remote(APP, V, own)
    a.save_file(APP, V, RUN_STATE_FILE, FINISHED)
    a.append_log_entry(APP, V, own, tag(2, "k2"))  # its ship failed
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    a.append_log_entry(APP, V, own, tag(3, "k3"))  # after the copy
    copy = cached_host(tmp_path, "a2")
    copy.sync_log_to_remote(APP, V, stream(copy))  # run end: ships, compacts

    cached_host(tmp_path, "a").sync_log_to_remote(APP, V, own)

    assert _remote_tag_counts() == {"k1": 1, "k2": 1, "k3": 1}
    fresh = cached_host(tmp_path, "fresh").load_merged_log(APP, V)
    assert sorted(k for e in fresh if e.get("type") == "tags" for k in e["set"]) == [
        "k1", "k2", "k3"]
