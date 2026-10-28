"""The threads a remote index's in-process load reads records in (plan 28
appendix A row 6).

On a free-threaded build a collection stops the world and waits for every
thread, so more CPU-bound load threads than cores only lengthen the pauses:
there the pool is capped at the cores this process may use. A GIL build
runs one of them at a time anyway and keeps them all for the network
waits. A cold load reads its records a chunk at a time through one pool,
not a new one per chunk."""
import threading
import time

from cold_store import APP, ColdStore

from vmn_exp.core import index as index_module
from vmn_exp.core import index_load_pool
from vmn_exp.core.index import ExperimentIndex


def test_a_free_threaded_build_caps_the_load_threads_at_the_cores(monkeypatch):
    monkeypatch.setattr(index_load_pool, "free_threaded", lambda: True)
    monkeypatch.setattr(index_load_pool, "cores", lambda: 8)
    assert index_load_pool.load_threads(32) == 8
    monkeypatch.setattr(index_load_pool, "cores", lambda: 64)
    assert index_load_pool.load_threads(32) == 32


def test_a_gil_build_keeps_every_load_thread(monkeypatch):
    monkeypatch.setattr(index_load_pool, "free_threaded", lambda: False)
    monkeypatch.setattr(index_load_pool, "cores", lambda: 4)
    assert index_load_pool.load_threads(32) == 32


def test_cores_are_the_ones_this_process_may_use(monkeypatch):
    monkeypatch.setattr(index_load_pool.os, "process_cpu_count", lambda: 3, raising=False)
    monkeypatch.setattr(index_load_pool.os, "cpu_count", lambda: 16)
    assert index_load_pool.cores() == 3
    monkeypatch.delattr(index_load_pool.os, "process_cpu_count", raising=False)
    assert index_load_pool.cores() == 16
    monkeypatch.setattr(index_load_pool.os, "cpu_count", lambda: None)
    assert index_load_pool.cores() == 1


def test_free_threaded_follows_the_interpreter(monkeypatch):
    monkeypatch.setattr(index_load_pool.sys, "_is_gil_enabled", lambda: False, raising=False)
    assert index_load_pool.free_threaded()
    monkeypatch.setattr(index_load_pool.sys, "_is_gil_enabled", lambda: True, raising=False)
    assert not index_load_pool.free_threaded()
    monkeypatch.delattr(index_load_pool.sys, "_is_gil_enabled", raising=False)
    assert not index_load_pool.free_threaded()


def _counted_pools(monkeypatch):
    made, real = [], index_load_pool.ThreadPoolExecutor

    def counted(*args, **kwargs):
        made.append(kwargs.get("max_workers", args[0] if args else None))
        return real(*args, **kwargs)

    monkeypatch.setattr(index_load_pool, "ThreadPoolExecutor", counted)
    return made


def _cold_load(tmp_path, n):
    index = ExperimentIndex(ColdStore(n), APP, cache_path=str(tmp_path / "idx.sqlite"))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        index.refresh()
        snap = index.published
        if snap is not None and len(snap.rows) == n and index.freshness()["phase"] == "idle":
            return index
    raise AssertionError("the cold load did not finish")


def _load_threads():
    return [t for t in threading.enumerate() if t.name.startswith("vmn-index-load")]


def test_a_cold_load_reads_every_chunk_through_one_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", 50)
    made = _counted_pools(monkeypatch)
    _cold_load(tmp_path, 600)
    assert len(made) == 1, made


def test_the_pool_is_capped_and_ends_with_the_load(tmp_path, monkeypatch):
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", 50)
    monkeypatch.setattr(index_load_pool, "free_threaded", lambda: True)
    monkeypatch.setattr(index_load_pool, "cores", lambda: 3)
    made = _counted_pools(monkeypatch)
    _cold_load(tmp_path, 600)
    assert made and set(made) == {3}
    deadline = time.monotonic() + 5
    while _load_threads() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _load_threads() == []
