"""E2: warm pure-S3 reader — 0 GET/HEAD on unchanged records, LIST count bound.

Build the index in one ExperimentIndex (simulating a previous process), then
a fresh storage + index object reads from the persisted SQLite: no object reads
should be needed for unchanged records, and the total LIST count should be
bounded by ceil(N*8/1000)+2 for N runs.
"""
import math

import pytest
from s3_helpers import mocked_bucket, op_counts, record_calls, s3_storage

moto = pytest.importorskip("moto")

from vmn_exp.core.index import ExperimentIndex, indexed_snapshot  # noqa: E402

APP = "myapp"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def s3_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", str(tmp_path / "cache"))
    with mocked_bucket(monkeypatch):
        yield tmp_path


def _seed(storage, n=3):
    """Write *n* minimal experiment records to *storage*."""
    verstrs = []
    for i in range(n):
        v = f"0.0.{i}"
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
        storage.append_log_entry(
            APP,
            v,
            "w0",
            {"timestamp": "2026-01-01T00:01:00Z", "type": "metrics", "values": {"loss": float(i)}},
        )
        storage.save_file(APP, v, "run_state.yml", "state: succeeded\nexit_code: 0\n")
        verstrs.append(v)
    return verstrs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_warm_new_process_zero_gets(s3_env):
    """Fresh index object with warm SQLite: 0 GETs, LISTs within bound."""
    n = 10
    storage1 = s3_storage()
    _seed(storage1, n)
    cache = storage1.index_cache_path(APP)
    assert cache is not None, "E1 must provide index_cache_path for S3"

    idx1 = ExperimentIndex(storage1, APP, cache_path=cache)
    idx1.refresh()
    assert len(idx1.rows()) == n

    # Simulate a new process: fresh storage + fresh ExperimentIndex reading the same SQLite
    storage2 = s3_storage()
    calls = record_calls(storage2._s3)
    idx2 = ExperimentIndex(storage2, APP, cache_path=cache)
    idx2.refresh()

    counts = op_counts(calls)
    assert counts["GetObject"] == 0, f"Expected 0 GETs, got {counts['GetObject']}"
    assert counts["HeadObject"] == 0, f"Expected 0 HEADs, got {counts['HeadObject']}"
    max_lists = math.ceil(n * 8 / 1000) + 2
    assert counts["ListObjectsV2"] <= max_lists, (
        f"Expected <= {max_lists} LISTs, got {counts['ListObjectsV2']}"
    )
    assert len(idx2.rows()) == n


def test_changed_record_reads_only_its_files(s3_env):
    """After a record's log grows, only that record's log is re-read."""
    storage = s3_storage()
    verstrs = _seed(storage, 3)
    cache = storage.index_cache_path(APP)
    assert cache is not None

    idx1 = ExperimentIndex(storage, APP, cache_path=cache)
    idx1.refresh()

    # Simulate new process; change one record
    storage2 = s3_storage()
    storage2.append_log_entry(
        APP,
        verstrs[1],
        "w0",
        {"timestamp": "2026-01-01T00:02:00Z", "type": "metrics", "values": {"acc": 0.99}},
    )
    calls = record_calls(storage2._s3)
    idx2 = ExperimentIndex(storage2, APP, cache_path=cache)
    idx2.refresh()

    counts = op_counts(calls)
    # Only the changed record needs a ranged GET (for the new log bytes)
    assert counts["GetObject"] <= 2, f"Expected <=2 GETs for one changed record, got {counts['GetObject']}"
    assert counts["HeadObject"] == 0
    rows = idx2.rows()
    assert len(rows) == 3
    changed = next(r for r in rows if r["verstr"] == verstrs[1])
    assert changed["metrics"]["acc"] == pytest.approx(0.99)


def test_pruned_elsewhere_dropped_from_store(s3_env):
    """A record deleted on S3 is removed from SQLite on next refresh."""
    storage = s3_storage()
    verstrs = _seed(storage, 3)
    cache = storage.index_cache_path(APP)
    assert cache is not None

    idx1 = ExperimentIndex(storage, APP, cache_path=cache)
    idx1.refresh()
    assert len(idx1.rows()) == 3

    # Delete one record from S3 (another host pruning)
    storage.delete(APP, verstrs[1])

    storage2 = s3_storage()
    idx2 = ExperimentIndex(storage2, APP, cache_path=cache)
    idx2.refresh()

    assert len(idx2.rows()) == 2
    assert not any(r["verstr"] == verstrs[1] for r in idx2.rows())


def test_cli_list_pure_s3_warm(s3_env):
    """indexed_snapshot (the list path) with pure S3: second call costs 0 GETs."""
    storage = s3_storage()
    _seed(storage, 5)
    cache = storage.index_cache_path(APP)
    assert cache is not None

    # First build (cold)
    snap1 = indexed_snapshot(storage, APP, cache_path=cache, wait=True)
    assert len(snap1.rows) == 5

    # Second call: new storage object simulates a new process
    storage2 = s3_storage()
    calls = record_calls(storage2._s3)
    snap2 = indexed_snapshot(storage2, APP, cache_path=cache, wait=True)
    counts = op_counts(calls)
    assert len(snap2.rows) == 5
    assert counts["GetObject"] == 0, f"Expected 0 GETs on warm S3 list, got {counts['GetObject']}"
    assert counts["HeadObject"] == 0
