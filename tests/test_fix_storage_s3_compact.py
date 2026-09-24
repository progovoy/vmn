"""Log segments get compacted when a run finishes, and no reader ever counts an
entry twice while the merged object and its segments coexist."""
import pytest
import yaml
from s3_helpers import (
    cached_host,
    concurrently,
    entry,
    meta,
    mocked_bucket,
    raw_keys,
    s3_storage,
)

from version_stamp.core.experiment_index import ExperimentIndex, direct_rows
from version_stamp.core.experiment_logfiles import (
    compacted_log_name,
    group_log_names,
    log_writer_and_seq,
)

V = "v"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _log_keys():
    return [k.rsplit("/", 1)[1] for k in raw_keys() if "/log." in k]


def _host_with_segments(tmp_path, n=3):
    host = cached_host(tmp_path, "a")
    host.save("app", V, meta(V), {})
    for i in range(n):
        host.append_log_entry("app", V, "w", entry(i))
        host.sync_log_to_remote("app", V, "w")
    return host


def _values(storage):
    return [e["values"]["i"] for e in storage.load_merged_log("app", V)]


def test_compacted_name_covers_the_segments_it_merged():
    name = compacted_log_name("w", 5)
    assert log_writer_and_seq(name) == ("w", 5)
    names = ["log.w.jsonl", "log.w@000003.jsonl", name, "log.w@000006.jsonl"]
    assert group_log_names(names) == {"w": [name, "log.w@000006.jsonl"]}


def test_compaction_merges_a_writers_segments_into_one_object(tmp_path):
    _host_with_segments(tmp_path)
    s3 = s3_storage()
    s3.compact_log_segments("app", V, "w")
    assert _log_keys() == [compacted_log_name("w", 2)]
    assert _values(s3) == [0, 1, 2]


def test_compaction_of_a_single_object_changes_nothing(tmp_path):
    _host_with_segments(tmp_path, n=1)
    s3_storage().compact_log_segments("app", V, "w")
    assert _log_keys() == ["log.w.jsonl"]


def test_readers_do_not_double_count_mid_compaction(tmp_path, monkeypatch):
    _host_with_segments(tmp_path)
    s3 = s3_storage()
    index = ExperimentIndex(s3, "app")
    index.refresh()
    # Crash between the merged PUT and the deletes: both copies stay listed.
    monkeypatch.setattr(s3, "_delete_keys", lambda keys: None)
    s3.compact_log_segments("app", V, "w")
    assert len(_log_keys()) == 4
    assert _values(s3) == [0, 1, 2]
    index.refresh()
    assert index.rows() == direct_rows(s3, "app")[0]
    assert index.rows()[0]["metrics"] == {"i": 2}


def test_sync_after_compaction_appends_a_later_segment(tmp_path):
    host = _host_with_segments(tmp_path)
    s3_storage().compact_log_segments("app", V, "w")
    host.append_log_entry("app", V, "w", entry(3))
    host.sync_log_to_remote("app", V, "w")
    fresh = cached_host(tmp_path, "b")
    assert _values(fresh) == [0, 1, 2, 3]
    restarted = cached_host(tmp_path, "a")
    restarted.append_log_entry("app", V, "w", entry(4))
    restarted.sync_log_to_remote("app", V, "w")
    assert _values(s3_storage()) == [0, 1, 2, 3, 4]


def test_the_final_sync_of_a_finished_run_compacts(tmp_path):
    host = _host_with_segments(tmp_path)
    host.append_log_entry("app", V, "w", entry(3))
    host.save_file("app", V, "run_state.yml", yaml.dump({"state": "finished"}))
    host.sync_log_to_remote("app", V, "w")
    assert _log_keys() == [compacted_log_name("w", 3)]
    assert _values(s3_storage()) == [0, 1, 2, 3]


def test_a_running_runs_sync_does_not_compact(tmp_path):
    host = _host_with_segments(tmp_path)
    host.save_file("app", V, "run_state.yml", yaml.dump({"state": "running"}))
    host.append_log_entry("app", V, "w", entry(3))
    host.sync_log_to_remote("app", V, "w")
    assert len(_log_keys()) == 4


def test_segments_are_fetched_concurrently(tmp_path):
    _host_with_segments(tmp_path)
    s3 = s3_storage()
    real, together = s3._s3.get_object, concurrently(3, s3._s3.get_object)
    s3._s3.get_object = lambda **kw: (
        together(**kw) if "/log.w" in kw["Key"] else real(**kw)
    )
    assert _values(s3) == [0, 1, 2]


def test_compaction_does_not_touch_other_writers(tmp_path):
    host = _host_with_segments(tmp_path, n=2)
    host.append_log_entry("app", V, "x", entry(9))
    host.sync_log_to_remote("app", V, "x")
    s3_storage().compact_log_segments("app", V, "w")
    assert sorted(_log_keys()) == [compacted_log_name("w", 1), "log.x.jsonl"]


def test_the_index_does_not_fold_a_merged_object_on_top_of_its_parts(
    tmp_path, monkeypatch
):
    _host_with_segments(tmp_path)
    s3 = s3_storage()
    index = ExperimentIndex(s3, "app").refresh()
    monkeypatch.setattr(s3, "_delete_keys", lambda keys: None)
    s3.compact_log_segments("app", V, "w")
    index.refresh()
    fresh = ExperimentIndex(s3, "app").refresh()
    assert index._records[V]["counts"] == fresh._records[V]["counts"] == {"w": 3}
