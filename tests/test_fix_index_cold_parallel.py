"""Cold start at 100k records took ~50s: ~19s of it one thread scanning
every record directory, ~26s loading the records in at most 8 worker
processes on a 16-core box. A large full listing scans on several threads
(each scandir/stat releases the GIL, so the syscalls overlap), and a cold
build uses a worker per CPU."""
import os
import threading

from vmn_exp.core import index_workers
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage import listing

APP = "app"


def _seed(root, n):
    st = LocalSnapshotStorage(str(root), subdir="experiments")
    for i in range(n):
        v = f"0.0.1-dev.abc.r{i}"
        st.save(APP, v, {"verstr": v, "timestamp": f"t{i}"}, {})
    return st


def test_a_large_full_listing_scans_on_several_threads(tmp_path, monkeypatch):
    st = _seed(tmp_path, listing.PARALLEL_MIN_DIRS * 2)
    threads = set()
    real = listing.files_in

    def tracking(path):
        threads.add(threading.get_ident())
        return real(path)

    monkeypatch.setattr(listing, "files_in", tracking)
    monkeypatch.setattr(LocalSnapshotStorage, "_files_in", staticmethod(tracking))
    listed = st.list_files(APP)

    assert len(listed) == listing.PARALLEL_MIN_DIRS * 2
    assert len(threads) > 1


def test_a_small_full_listing_stays_on_the_calling_thread(tmp_path, monkeypatch):
    st = _seed(tmp_path, 3)
    threads = set()
    real = listing.files_in

    def tracking(path):
        threads.add(threading.get_ident())
        return real(path)

    monkeypatch.setattr(listing, "files_in", tracking)
    monkeypatch.setattr(LocalSnapshotStorage, "_files_in", staticmethod(tracking))
    assert len(st.list_files(APP)) == 3
    assert threads == {threading.get_ident()}


def test_a_cold_build_starts_a_worker_per_cpu(monkeypatch):
    monkeypatch.setattr(index_workers, "_cpus", lambda: 16)
    work = [(f"k{i}", {}, None) for i in range(16 * index_workers.RECORDS_PER_WORKER)]
    counts = []
    monkeypatch.setattr(index_workers, "_can_spawn", lambda: True)
    monkeypatch.setattr(index_workers, "_with_record_dirs",
                        lambda *a: [(k, os.sep, n) for k, n, _ in work])
    monkeypatch.setattr(index_workers, "_run_worker",
                        lambda app, chunk: counts.append(len(chunk)) or [])
    index_workers.load_new_records(None, None, APP, work)
    assert len(counts) == 16


def _track(monkeypatch, owner, name, wrap=lambda f: f):
    threads = set()
    real = getattr(owner, name)

    def tracking(*args):
        threads.add(threading.get_ident())
        return real(*args)

    monkeypatch.setattr(owner, name, wrap(tracking))
    return threads


def test_a_large_keyed_listing_scans_on_several_threads(tmp_path, monkeypatch):
    st = _seed(tmp_path, listing.PARALLEL_MIN_DIRS * 2)
    keys = [f"0.0.1-dev.abc.r{i}" for i in range(listing.PARALLEL_MIN_DIRS * 2)]
    threads = _track(monkeypatch, LocalSnapshotStorage, "_files_in", staticmethod)
    assert len(st.list_files(APP, keys=keys)) == len(keys)
    assert len(threads) > 1


def test_a_large_names_listing_stats_on_several_threads(tmp_path, monkeypatch):
    from vmn_exp.storage import local

    st = _seed(tmp_path, listing.PARALLEL_MIN_DIRS * 2)
    threads = _track(monkeypatch, local, "_dir_sig")
    assert len(st.list_record_names(APP)) == listing.PARALLEL_MIN_DIRS * 2
    assert len(threads) > 1
