#!/usr/bin/env python3
"""The run detail's store reads, in flight together.

On S3 each read of a run detail is a round trip (30 ms on a bench: 20 reads
in turn made an outer run's detail 0.76 s). Once the run's name is resolved,
its metadata, log, artifact listing, ``env.yml``, metric objects and the run
states (with their store write times) of its subtree do not depend on each
other, so they are submitted to one shared pool at once and the payload is
assembled from the answers — the same payload a sequential reader builds.

:class:`RunStates` is a per-request memo: the tree and fleet derivations ask
for a member's state and write time more than once, and each is read once.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

WORKERS = 32
# Subtree members whose states are prefetched; the rest are read on demand.
PREFETCH_MAX = 256

_POOL = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="vmn-ui-detail")


def submit(fn, *args, **kwargs):
    return _POOL.submit(fn, *args, **kwargs)


class RunStates:
    """``read_run_state``/``read_observed_at`` with the signatures of the
    loaders they wrap, each ``(kind, verstr)`` read once."""

    def __init__(self, storage, app_name, read_run_state, read_observed_at):
        self._storage, self._app = storage, app_name
        self._readers = {"state": read_run_state, "observed": read_observed_at}
        self._futures = {}
        self._lock = threading.Lock()

    def prefetch(self, verstrs):
        for verstr in list(verstrs)[:PREFETCH_MAX]:
            self._future("state", verstr)
            self._future("observed", verstr)

    def _future(self, kind, verstr):
        key = (kind, verstr)
        with self._lock:
            future = self._futures.get(key)
            if future is None:
                future = self._futures[key] = submit(
                    self._readers[kind], self._storage, self._app, verstr)
        return future

    def read_run_state(self, storage, app_name, verstr):
        return self._future("state", verstr).result()

    def read_observed_at(self, storage, app_name, verstr):
        return self._future("observed", verstr).result()
