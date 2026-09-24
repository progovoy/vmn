"""A cold ExperimentIndex build: the same rows as a direct read, whether the
records load in-process or in worker processes, persisted in one transaction
and reading every file once. Counts and compares — never times."""
import json
import os
import sqlite3
import sys

import pytest
import yaml

from version_stamp.cli.snapshot import LocalSnapshotStorage, get_snapshot_storage
from version_stamp.core import experiment_index_store, experiment_index_workers
from version_stamp.core import logging as vmn_logging
from version_stamp.core.experiment_index import ExperimentIndex, direct_rows

APP = "app"
TS = "2026-01-01T00:00:{:02d}Z"


@pytest.fixture(autouse=True)
def _logger():
    """The unparseable run state below is logged; restore whatever was there."""
    saved = vmn_logging._logger_holder[0]
    vmn_logging.ensure_logger()
    yield
    vmn_logging._logger_holder[0] = saved


def _storage(root):
    return get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")


def _dir(root, verstr):
    return os.path.join(str(root), ".vmn", APP, "experiments", verstr)


def _write(root, verstr, name, text):
    with open(os.path.join(_dir(root, verstr), name), "w", encoding="utf-8") as f:
        f.write(text)


def _record(storage, i, **meta):
    verstr = f"0.0.1-dev.abc.r{i}"
    storage.save(APP, verstr, dict({"verstr": verstr, "timestamp": TS.format(i)}, **meta), {})
    return verstr


def _seed(root):
    """Records exercising every log shape the fold reads."""
    storage = _storage(root)
    for i in range(12):
        verstr = _record(storage, i, note=f"note {i}" if i % 3 else None, parent=None)
        storage.append_log_entries(APP, verstr, "w0", [
            {"timestamp": TS.format(i), "type": "create", "note": f"c{i}",
             "params": {"lr": 0.1 * i, "opt": "adam", "missing": "nan"}},
            {"timestamp": TS.format(i), "type": "metrics", "values": {"loss": 1.0 / (i + 1)}},
        ])
        if i % 2:
            storage.save_file(APP, verstr, "run_state.yml", f"state: finished\nexit_code: {i % 3}\n")
    # NaN / Infinity tokens, big ints, non-ASCII, corrupt and non-object lines.
    _write(root, "0.0.1-dev.abc.r0", "log.w1.jsonl",
           '{"timestamp": "2026-01-01T00:01:00Z", "type": "metrics", "values": {"loss": NaN, "acc": Infinity}}\n'
           '{"type": "metrics", "values": {"seed": 123456789012345678901234567890}}\n'
           '{"type": "params", "params": {"name": "café ☃"}}\n'
           'not json\n[1, 2]\n{"a": 1} {"b": 2}\n﻿{"type": "metrics", "values": {"x": 1}}\n'
           '   {"type": "metrics", "values": {"y": -Infinity}}   \n\n')
    # Segments of a second writer and an unterminated last line.
    _write(root, "0.0.1-dev.abc.r1", "log.w2@000001.jsonl", '{"type": "metrics", "values": {"s": 1}}\n')
    _write(root, "0.0.1-dev.abc.r1", "log.w2@000002.jsonl", '{"type": "metrics", "values": {"s": 2}}')
    # The legacy log.yml, next to a JSONL writer.
    _write(root, "0.0.1-dev.abc.r2", "log.yml", yaml.safe_dump(
        [{"timestamp": "2025-12-31T00:00:00Z", "type": "create", "note": "legacy",
          "params": {"lr": 5}}, {"type": "metrics", "values": {"legacy": 1.5}}]))
    # A hand-edited run state, a YAML-typed metadata field, a verinfo file.
    _write(root, "0.0.1-dev.abc.r3", "run_state.yml", "state: [unclosed\n")
    _write(root, "0.0.1-dev.abc.r4", "run_state.yml", "- just\n- a list\n")
    _record(storage, 20, when=None, archived=True, user_meta={"k": [1, 2.5, "x"]})
    os.makedirs(_dir(root, "legacy_verinfo"))
    _write(root, "legacy_verinfo", "metadata.yml", "stamping: {}\n")
    os.makedirs(_dir(root, "claim_without_metadata"))
    _write(root, "claim_without_metadata", "log.w.jsonl", '{"type": "metrics"}\n')
    return storage


def _exact(value):
    """*value* as text: types kept (1 is not 1.0 or True), row order kept, and
    a NaN equals a NaN — a worker's is not the same object as the parser's."""
    return json.dumps(value, sort_keys=True, default=repr)


def _expected(storage):
    return _exact(direct_rows(storage, APP, with_create_note=True))


def _cold(storage, tmp_path, name="index.sqlite"):
    index = ExperimentIndex(storage, APP, cache_path=str(tmp_path / name)).refresh()
    return _exact((index.rows(with_create_note=True), index.run_states()))


@pytest.fixture
def spawned(monkeypatch):
    """Every worker process started, as its command line."""
    calls = []
    real = experiment_index_workers._spawn

    def counted(cmd, env):
        calls.append(cmd)
        return real(cmd, env)

    monkeypatch.setattr(experiment_index_workers, "_spawn", counted)
    return calls


@pytest.fixture
def workers_for_any_size(monkeypatch):
    monkeypatch.setattr(experiment_index_workers, "MIN_RECORDS", 1)
    monkeypatch.setattr(experiment_index_workers, "RECORDS_PER_WORKER", 3)


def test_an_in_process_cold_build_matches_the_direct_read(tmp_path, spawned):
    storage = _seed(tmp_path / "repo")

    assert _cold(storage, tmp_path) == _expected(storage)
    assert spawned == []  # a dozen records are not worth a process


def test_a_cold_build_in_worker_processes_matches_the_direct_read(
    tmp_path, spawned, workers_for_any_size
):
    storage = _seed(tmp_path / "repo")

    cold = _cold(storage, tmp_path)

    assert cold == _expected(storage)
    assert len(spawned) >= 2
    # What the workers folded persists like an in-process build.
    assert _cold(storage, tmp_path) == cold


def test_worker_rows_equal_in_process_rows_including_the_persisted_index(
    tmp_path, monkeypatch, spawned
):
    storage = _seed(tmp_path / "repo")
    in_process = _cold(storage, tmp_path, "a.sqlite")
    monkeypatch.setattr(experiment_index_workers, "MIN_RECORDS", 1)
    monkeypatch.setattr(experiment_index_workers, "RECORDS_PER_WORKER", 3)

    assert _cold(storage, tmp_path, "b.sqlite") == in_process
    assert spawned
    assert _persisted(tmp_path / "b.sqlite") == _persisted(tmp_path / "a.sqlite")


def _persisted(path):
    conn = sqlite3.connect(str(path))
    try:
        return [
            sorted(conn.execute(f"SELECT key, data FROM {table}").fetchall())
            for table in ("exp_index", "exp_index_state")
        ]
    finally:
        conn.close()


def test_a_failing_worker_falls_back_to_loading_in_process(
    tmp_path, monkeypatch, spawned, workers_for_any_size
):
    storage = _seed(tmp_path / "repo")
    monkeypatch.setattr(
        experiment_index_workers, "_worker_command",
        lambda: [sys.executable, "-c", "import sys; sys.exit(3)"],
    )

    assert _cold(storage, tmp_path) == _expected(storage)
    assert spawned


def test_a_worker_that_cannot_start_falls_back_to_loading_in_process(
    tmp_path, monkeypatch, workers_for_any_size
):
    storage = _seed(tmp_path / "repo")
    monkeypatch.setattr(
        experiment_index_workers, "_worker_command",
        lambda: [str(tmp_path / "no-such-python")],
    )

    assert _cold(storage, tmp_path) == _expected(storage)


class _ReadingStorage(LocalSnapshotStorage):
    """A subclass may read differently: its records are never handed to workers."""


def test_a_storage_subclass_is_loaded_in_process(tmp_path, spawned, workers_for_any_size):
    _seed(tmp_path / "repo")
    storage = _ReadingStorage(str(tmp_path / "repo"), subdir="experiments")

    assert _cold(storage, tmp_path) == _expected(storage)
    assert spawned == []


def test_a_warm_index_never_starts_workers(tmp_path, spawned, workers_for_any_size):
    storage = _seed(tmp_path / "repo")
    _cold(storage, tmp_path)
    spawned.clear()

    assert _cold(storage, tmp_path) == _expected(storage)
    assert spawned == []


def test_a_cold_build_persists_in_one_transaction(tmp_path, monkeypatch):
    storage = _seed(tmp_path / "repo")
    statements = []
    real = experiment_index_store._connect

    def traced(path):
        conn = real(path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(experiment_index_store, "_connect", traced)

    _cold(storage, tmp_path)

    commits = [s for s in statements if s.strip().upper().startswith("COMMIT")]
    assert len(commits) == 1, statements


def test_a_cold_build_reads_every_file_once(tmp_path, monkeypatch):
    storage = _seed(tmp_path / "repo")
    reads = []
    real_tail, real_load = LocalSnapshotStorage.read_file_from, LocalSnapshotStorage.load_file

    def tail(self, app_name, verstr, filename, offset):
        reads.append((verstr, filename))
        return real_tail(self, app_name, verstr, filename, offset)

    def load(self, app_name, verstr, filename):
        reads.append((verstr, filename))
        return real_load(self, app_name, verstr, filename)

    monkeypatch.setattr(LocalSnapshotStorage, "read_file_from", tail)
    monkeypatch.setattr(LocalSnapshotStorage, "load_file", load)

    _cold(storage, tmp_path)

    assert reads and len(reads) == len(set(reads)), sorted(reads)


def test_a_full_listing_does_not_stat_each_metadata_file_again(tmp_path, monkeypatch):
    storage = _seed(tmp_path / "repo")
    local = LocalSnapshotStorage(str(tmp_path / "repo"), subdir="experiments")
    expected_keys = {m["verstr"] for m in storage.list_snapshots(APP)} | {"legacy_verinfo"}
    checks = []
    real_isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: checks.append(p) or real_isfile(p))

    listing = local.list_files(APP)

    assert set(listing) == expected_keys
    assert checks == []
