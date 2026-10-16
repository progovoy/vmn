"""A warm start's lazy records are refreshed from a thread pool: a record whose
chunk another thread is still reading must wait for it, never read as gone."""
import threading
import time

from vmn_exp.core.index_store_reads import _Prefetch


class _SlowStore:
    def __init__(self):
        self.calls = 0

    def records_parts(self, app_name, seqs):
        self.calls += 1
        time.sleep(0.05)  # the first thread is still reading when the others ask
        return {key: (f"head-{key}", f"data-{key}") for key in seqs}


def test_threads_asking_for_one_chunk_all_get_their_parts():
    store = _SlowStore()
    keys = [f"k{i}" for i in range(8)]
    fetch = _Prefetch(store, "app", {key: 1 for key in keys})
    got = {}
    threads = [threading.Thread(target=lambda k=k: got.__setitem__(k, fetch(k))) for k in keys]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert got == {key: (f"head-{key}", f"data-{key}") for key in keys}
    assert store.calls == 1
