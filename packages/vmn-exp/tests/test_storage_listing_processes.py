"""A very large full listing of a local store scans in worker processes
(plan 23 S9).

At 100k records a full listing took ~17s on 16 threads — barely less than
on one: each scandir/stat hands the GIL over, and the threads queue for it.
Processes scale (~5s on 12). The workers scan with the same code, honour
the settled listings the parent knows and hand back what it should keep;
one that fails leaves its directories to the in-process scan.
"""
import os
import time

import pytest

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage import listing, listing_workers

APP = "app"
RUNS = 40
HOUR_NS = 3600 * 10**9


def _seed(root):
    st = LocalSnapshotStorage(str(root), area="runs")
    for i in range(RUNS):
        verstr = f"0.0.1-dev.abc.r{i}"
        st.save(APP, verstr, {"verstr": verstr, "timestamp": f"t{i}"}, {})
        st.append_log_entry(APP, verstr, "w", {"type": "metrics", "values": {"i": i}})
        if i % 2:
            st.save_file(APP, verstr, "run_state.yml", "state: finished\nexit_code: 0\n")
        _age(st.plain_record_dir(APP, verstr))
    return st


def _age(path):
    then = time.time_ns() - HOUR_NS
    for sub in ("log", ""):
        os.utime(os.path.join(path, sub), ns=(then, then))


@pytest.fixture
def spawned(monkeypatch):
    """The directory count each worker process was handed."""
    counts = []
    real = listing_workers._run_worker

    def counting(items, identity):
        counts.append(len(items))
        return real(items, identity)

    monkeypatch.setattr(listing_workers, "_run_worker", counting)
    monkeypatch.setattr(listing, "PROCESS_MIN_DIRS", 10)
    monkeypatch.setattr(listing_workers, "DIRS_PER_WORKER", 10)
    return counts


def _in_process(root, identity=False):
    return LocalSnapshotStorage(str(root), area="runs").list_files(APP, identity=identity)


@pytest.mark.parametrize("identity", [False, True])
def test_a_large_listing_scans_in_processes_with_the_same_result(
    tmp_path, spawned, monkeypatch, identity
):
    st = _seed(tmp_path)

    listed = st.list_files(APP, identity=identity)

    assert len(spawned) > 1 and sum(spawned) == RUNS
    monkeypatch.setattr(listing, "PROCESS_MIN_DIRS", 10**9)
    assert listed == _in_process(tmp_path, identity)


def test_what_the_workers_scanned_settles_for_the_next_listing(tmp_path, spawned, monkeypatch):
    st = _seed(tmp_path)
    first = st.list_files(APP)
    monkeypatch.setattr(listing, "PROCESS_MIN_DIRS", 10**9)
    scans = []
    real = os.scandir
    monkeypatch.setattr(os, "scandir", lambda path=".": scans.append(path) or real(path))

    assert st.list_files(APP) == first
    assert len(scans) == 1  # the base directory only


def test_the_workers_reuse_the_settled_listings(tmp_path, spawned):
    st = _seed(tmp_path)
    st.list_files(APP)
    verstr = "0.0.1-dev.abc.r3"
    st.append_log_entry(APP, verstr, "w", {"type": "metrics", "values": {"i": 99}})
    _age(st.plain_record_dir(APP, verstr))
    log = os.path.join(st.plain_record_dir(APP, verstr), "log", "w.jsonl")

    assert st.list_files(APP)[verstr]["log/w.jsonl"][0] == os.path.getsize(log)


def test_a_failing_worker_leaves_its_directories_to_the_in_process_scan(
    tmp_path, spawned, monkeypatch
):
    st = _seed(tmp_path)
    monkeypatch.setattr(listing_workers, "_worker_command", lambda: ["false"])

    listed = st.list_files(APP)

    monkeypatch.setattr(listing, "PROCESS_MIN_DIRS", 10**9)
    assert listed == _in_process(tmp_path)


def test_a_small_listing_starts_no_process(tmp_path, monkeypatch):
    st = _seed(tmp_path)
    monkeypatch.setattr(listing_workers, "_run_worker", lambda *a: pytest.fail("spawned"))

    assert len(st.list_files(APP)) == RUNS
