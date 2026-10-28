"""A record a bulk load's worker process could not read because the store
refused it (S3 ``SlowDown`` past botocore's retries) is set aside, not read
again in-process: that re-read was ~4 more GETs, each retried, straight at
the store that had just refused them — under a SlowDown burst during a cold
load of thousands of records, about twice the refused requests. A record
that fails otherwise is still read in-process, as before."""
import logging
import os
from collections import Counter

import pytest
from botocore.exceptions import ClientError
from cold_store import APP, ColdStore

import vmn_exp.core.index as index_module
from vmn_exp.core import index_remote_workers
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_remote_workers import RemoteLoaders
from vmn_exp.core.index_unreadable import Unreadable

TESTS = os.path.dirname(os.path.abspath(__file__))


class ThrottledStore(ColdStore):
    """A ColdStore a worker opens again: *refused* keys' reads raise
    ``SlowDown``, *broken* keys' a record error; in-process reads counted."""

    def __init__(self, n, refused=(), broken=()):
        super().__init__(n)
        self.refused, self.broken = set(refused), set(broken)
        self.reads = Counter()

    def worker_spec(self):
        return (__name__, "ThrottledStore",
                (len(self.names), sorted(self.refused), sorted(self.broken)), {})

    def load_file(self, app_name, key, filename):
        self.reads[key] += 1
        if key in self.refused:
            raise ClientError({"Error": {"Code": "SlowDown", "Message": "Reduce your request rate."}},
                              "GetObject")
        if key in self.broken:
            raise ValueError("half-written record")
        return super().load_file(app_name, key, filename)


@pytest.fixture(autouse=True)
def _importable(monkeypatch):
    path = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", TESTS + (os.pathsep + path if path else ""))
    monkeypatch.setattr(index_remote_workers, "worker_count", lambda: 2)


def _work(store):
    return [(key, store._record_files(key), None) for key in store.names]


def _load(store, unreadable):
    loaders = RemoteLoaders(store.worker_spec(), 2)
    try:
        return loaders.load(APP, _work(store), unreadable)
    finally:
        loaders.close()


def test_a_record_the_store_refused_a_worker_is_set_aside(caplog):
    store = ThrottledStore(100)
    refused = store.names[3]
    store.refused.add(refused)
    unreadable = Unreadable(APP, lambda: 0.0)

    with caplog.at_level(logging.WARNING, logger="vmn_exp.core.index"):
        done = _load(store, unreadable)

    assert refused in unreadable
    assert done[refused] == (None, False, False, False)
    assert done[store.names[4]][0] is not None
    assert "the store failed" in caplog.text and "SlowDown" in caplog.text


def test_a_set_aside_record_is_left_to_its_due_retry():
    store = ThrottledStore(100)
    aside = store.names[5]
    unreadable = Unreadable(APP, lambda: 0.0)
    unreadable.failed(aside, ValueError("earlier"))

    done = _load(store, unreadable)

    assert aside not in done
    assert len(done) == 99


def test_a_record_failing_otherwise_in_a_worker_is_left_to_the_caller():
    store = ThrottledStore(100)
    broken = store.names[7]
    store.broken.add(broken)
    unreadable = Unreadable(APP, lambda: 0.0)

    assert broken not in _load(store, unreadable)  # the caller reads it in-process
    assert broken not in unreadable


def _cold_load(store, tmp_path):
    index = ExperimentIndex(store, APP, cache_path=str(tmp_path / "idx.sqlite"), full_sweep_sec=3600)
    index.journaled = True
    index.reconcile()
    for _ in range(100):
        index.refresh()
        if len(index.published.rows) >= len(store.names) - 1 and index.freshness()["phase"] == "idle":
            break
    return index


def test_a_cold_load_does_not_reread_a_record_the_store_refused_a_worker(tmp_path, monkeypatch):
    store = ThrottledStore(1500)
    refused = store.names[-1]  # the newest: in the first chunk, read by the workers
    store.refused.add(refused)
    index = _cold_load(store, tmp_path)
    try:
        assert refused not in [r["verstr"] for r in index.rows()]
        assert store.reads[refused] == 0
        assert len(index.rows()) == 1499

        store.refused.clear()
        monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 0)
        index.refresh()
        assert store.reads[refused] > 0
        assert refused in [r["verstr"] for r in index.rows()]
    finally:
        index.close()
