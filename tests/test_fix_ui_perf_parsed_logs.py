"""The run-detail log cache: a grown local log costs its new bytes, the result
always equals a full parse, and the cache is bounded by size."""
import json
import os

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage, get_snapshot_storage
from version_stamp.core.experiment_log import (
    effective_params,
    last_metric_at,
    latest_metrics,
    load_log,
    metric_series,
)
from version_stamp.ui.readers import parsed_logs
from version_stamp.ui.readers.parsed_logs import ParsedLogs

APP = "app"
V = "1.0.0-dev.a"


def _ts(i):
    return f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _metric(i, **values):
    return {"timestamp": _ts(i), "type": "metrics", "step": i, "values": values or {"loss": i / 7}}


@pytest.fixture
def storage(tmp_path):
    (tmp_path / ".git").mkdir()
    s = get_snapshot_storage("local", vmn_root_path=str(tmp_path), subdir="experiments")
    s.save(APP, V, {"verstr": V, "timestamp": _ts(0)}, {})
    s.append_log_entry(APP, V, "w", {"timestamp": _ts(0), "type": "create", "params": {"lr": 0.1}})
    return s


def _append(storage, start, stop, writer="w", verstr=V):
    for i in range(start, stop):
        storage.append_log_entry(APP, verstr, writer, _metric(i))


def _assert_matches_full_parse(snap, storage, verstr=V):
    full = load_log(storage, APP, verstr)
    assert snap.log() == full
    assert snap.total == len(full)
    assert snap.series() == metric_series(full)
    assert snap.params == effective_params(full)
    assert snap.metrics == latest_metrics(full)
    assert snap.last_metric_at == last_metric_at(full)
    assert snap.tail(5) == full[-5:]
    assert snap.page(2, 3) == full[2:5]


def _log_path(storage, writer="w", verstr=V):
    return os.path.join(storage.direct_files()._snapshot_dir(APP, verstr), f"log.{writer}.jsonl")


def test_a_grown_log_is_read_from_the_saved_offset(storage, monkeypatch):
    cache = ParsedLogs()
    _append(storage, 1, 50)
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)
    size = os.path.getsize(_log_path(storage))

    offsets = []
    real_read = LocalSnapshotStorage.read_file_from

    def spy(self, app_name, verstr, filename, offset):
        offsets.append((filename, offset))
        return real_read(self, app_name, verstr, filename, offset)

    def no_full_read(*args, **kwargs):
        raise AssertionError("a grown log must not be re-read from the start")

    monkeypatch.setattr(LocalSnapshotStorage, "read_file_from", spy)
    monkeypatch.setattr(LocalSnapshotStorage, "load_merged_log", no_full_read)
    _append(storage, 50, 60)
    snap = cache.get(storage, APP, V, load_log)

    assert offsets == [("log.w.jsonl", size)]
    monkeypatch.undo()
    _assert_matches_full_parse(snap, storage)


def test_a_poll_parses_only_the_new_entries(storage, monkeypatch):
    cache = ParsedLogs()
    _append(storage, 1, 2000)
    cache.get(storage, APP, V, load_log)

    parsed = []
    real = parsed_logs.parse_jsonl

    def counting(text, writer):
        entries = real(text, writer)
        parsed.extend(entries)
        return entries

    monkeypatch.setattr(parsed_logs, "parse_jsonl", counting)
    _append(storage, 2000, 2003)
    snap = cache.get(storage, APP, V, load_log)
    assert len(parsed) == 3
    assert snap.total == 2000 + 3
    assert cache.get(storage, APP, V, load_log) is snap  # unchanged: a hit


def test_earlier_snapshots_are_not_changed_by_growth(storage):
    cache = ParsedLogs()
    _append(storage, 1, 10)
    old = cache.get(storage, APP, V, load_log)
    before = (old.log(), old.series(), old.metrics)
    _append(storage, 10, 20)
    cache.get(storage, APP, V, load_log)
    assert (old.log(), old.series(), old.metrics) == before
    assert old.total == 10


def test_several_writers_and_new_files_match_a_full_parse(storage):
    cache = ParsedLogs()
    _append(storage, 1, 10, writer="w")
    cache.get(storage, APP, V, load_log)
    _append(storage, 10, 15, writer="b")
    _append(storage, 15, 20, writer="w")
    _append(storage, 20, 22, writer="b")
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)


def test_out_of_order_growth_falls_back_to_a_full_parse(storage):
    cache = ParsedLogs()
    _append(storage, 10, 20)
    cache.get(storage, APP, V, load_log)
    _append(storage, 1, 5, writer="late")  # older timestamps, sort before
    _append(storage, 19, 20, writer="z")  # same timestamp as the last entry
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)


def test_a_half_written_line_is_picked_up_once_complete(storage):
    cache = ParsedLogs()
    _append(storage, 1, 5)
    cache.get(storage, APP, V, load_log)
    line = json.dumps(_metric(5))
    with open(_log_path(storage), "a") as f:
        f.write(line[:10])
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)
    with open(_log_path(storage), "a") as f:
        f.write(line[10:])  # complete JSON, no newline yet
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)
    with open(_log_path(storage), "a") as f:
        f.write("\n")
    _append(storage, 6, 8)
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)


def test_a_rewritten_or_shrunk_log_is_re_read(storage):
    cache = ParsedLogs()
    _append(storage, 1, 10)
    cache.get(storage, APP, V, load_log)
    with open(_log_path(storage), "w") as f:
        f.write(json.dumps(_metric(3)) + "\n")
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)


def test_a_legacy_log_yml_still_reads_correctly(storage):
    cache = ParsedLogs()
    storage.save_file(APP, V, "log.yml", "- {timestamp: '0', type: metrics, values: {x: 1}}\n")
    _append(storage, 1, 3)
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)
    _append(storage, 3, 5)
    _assert_matches_full_parse(cache.get(storage, APP, V, load_log), storage)


def test_the_cache_is_bounded_by_bytes(storage):
    for name in ("1.0.0-dev.b", "1.0.0-dev.c", "1.0.0-dev.d"):
        storage.save(APP, name, {"verstr": name, "timestamp": _ts(0)}, {})
        _append(storage, 1, 200, verstr=name)
    one = os.path.getsize(_log_path(storage, verstr="1.0.0-dev.b"))
    cache = ParsedLogs(max_bytes=int(one * 2.5))
    for name in ("1.0.0-dev.b", "1.0.0-dev.c", "1.0.0-dev.d"):
        cache.get(storage, APP, name, load_log)
    assert len(cache) == 2
    assert cache.bytes <= one * 2.5


def test_the_cache_is_bounded_by_entries(storage):
    cache = ParsedLogs(max_entries=1)
    storage.save(APP, "1.0.0-dev.b", {"verstr": "1.0.0-dev.b", "timestamp": _ts(0)}, {})
    cache.get(storage, APP, V, load_log)
    cache.get(storage, APP, "1.0.0-dev.b", load_log)
    assert len(cache) == 1


def test_a_custom_reader_is_honoured(storage):
    cache = ParsedLogs()
    custom = [_metric(1, acc=0.5)]
    snap = cache.get(storage, APP, V, lambda *a: list(custom))
    assert snap.log() == custom
    assert snap.series() == metric_series(custom)
