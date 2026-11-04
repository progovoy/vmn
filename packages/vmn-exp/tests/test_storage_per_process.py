"""Per-process storage state: a process whose pid changed (a forked child)
builds its own object-store client and module locks instead of using the
parent's, which a parent thread may hold or a parent connection may be on.
The pid change is simulated, so no process forks here."""
import os
import threading

import pytest
from object_store_fakes import FakeContainerClient, FakeGCSClient, install_fake_azure, install_fake_gcs


@pytest.fixture
def forked(monkeypatch):
    """Call it to make this process look like a forked child of itself."""
    real = os.getpid()

    def fork():
        monkeypatch.setattr(os, "getpid", lambda: real + 1)

    return fork


def _back_in_parent(monkeypatch):
    """The real pid again, to give back what the "parent" took."""
    monkeypatch.undo()


def test_per_process_builds_once_per_pid(forked):
    from vmn_exp.storage.per_process import PerProcess

    built = []
    value = PerProcess(lambda: built.append(object()) or built[-1])
    first = value.get()
    assert value.get() is first and len(built) == 1
    forked()
    child = value.get()
    assert child is not first and value.get() is child and len(built) == 2


def test_per_process_seeded_value_is_the_parents(forked):
    from vmn_exp.storage.per_process import PerProcess

    seed = object()
    value = PerProcess(object, value=seed)
    assert value.get() is seed
    forked()
    assert value.get() is not seed


def test_a_lock_a_parent_thread_holds_does_not_block_the_child(forked):
    from vmn_exp.storage.per_process import PerProcessLock

    lock = PerProcessLock()
    lock.__enter__()  # a parent thread held it at the fork
    forked()
    entered = threading.Event()

    def take():
        with lock:
            entered.set()

    t = threading.Thread(target=take, daemon=True)
    t.start()
    assert entered.wait(2), "the child blocked on the parent's lock"


def test_prefix_cap_and_stats_locks_are_per_process(forked, monkeypatch):
    from vmn_exp.storage import s3_prefix_cap, s3_stats

    s3_prefix_cap._lock.__enter__()
    s3_stats._lock.__enter__()
    forked()
    done = threading.Event()

    def use():
        cap = s3_prefix_cap._cap_of("bkt", "p")
        cap.acquire()
        cap.release()
        s3_prefix_cap.prefix_cap_stats()
        s3_stats.s3_stats()
        done.set()

    try:
        threading.Thread(target=use, daemon=True).start()
        assert done.wait(2), "the child blocked on a parent's module lock"
    finally:
        _back_in_parent(monkeypatch)
        s3_prefix_cap._lock.__exit__(None, None, None)
        s3_stats._lock.__exit__(None, None, None)


def test_prefix_cap_slots_the_parent_held_are_free_in_the_child(forked, monkeypatch):
    from vmn_exp.storage import s3_prefix_cap

    monkeypatch.setenv(s3_prefix_cap.ENV, "1")
    held = s3_prefix_cap._cap_of("bkt-held", "p")
    held.acquire()  # a parent call in flight
    forked()
    cap = s3_prefix_cap._cap_of("bkt-held", "p")
    try:
        assert cap.slots.acquire(timeout=1), "the child waited on the parent's slot"
        cap.slots.release()
    finally:
        _back_in_parent(monkeypatch)
        held.release()


def test_fanout_budget_is_full_again_in_the_child(forked, monkeypatch):
    import time

    from vmn_exp.storage import fanout

    taken = fanout._borrow(10_000)  # the parent's fan-outs hold the whole budget
    assert sum(n for _, n in taken) > 0
    forked()
    threads = set()

    def work(_):
        threads.add(threading.get_ident())
        time.sleep(0.05)

    try:
        fanout.fan_out(work, range(8), 8, "t")
        assert len(threads) > 1, "the child's fan-out ran alone on the parent's budget"
    finally:
        _back_in_parent(monkeypatch)
        for slots, n in taken:
            for _ in range(n):
                slots.release()


def test_gcs_store_builds_a_fresh_client_in_the_child(monkeypatch, forked):
    from vmn_exp.storage.registry import open_store

    install_fake_gcs(monkeypatch, None)
    import sys

    sys.modules["google.cloud.storage"].Client = lambda *a, **k: FakeGCSClient()
    store = open_store("gs://bkt/team", area="runs")
    clone = store._open_area("models")
    parent = store._s3
    forked()
    child = store._s3
    assert child is not parent and child._client is not parent._client
    assert clone._s3 is child
    assert not store.exists("trainer", "0.0.1-dev.a.b")  # it works


def test_gcs_store_on_an_injected_client_refuses_in_the_child(forked):
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    store = GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())
    forked()
    with pytest.raises(RuntimeError, match="fork"):
        store._s3


def test_azure_store_builds_a_fresh_container_client_in_the_child(monkeypatch, forked):
    from vmn_exp.storage.registry import open_store

    install_fake_azure(monkeypatch)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    store = open_store("az://ctr", area="runs")
    parent = store._s3
    forked()
    child = store._s3
    assert child is not parent and child._container is not parent._container
    assert isinstance(child._container, FakeContainerClient)
    assert child._if_not_modified == parent._if_not_modified
