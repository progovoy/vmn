"""A remote cold load reads its new records in worker processes: botocore
spends ~0.7 ms of CPU per GET under one GIL, which capped a cold S3 load
near 200 runs/s. Workers open the backend again from its ``worker_spec()``
and hand records back exactly as the index would have read them."""
import os

import pytest
from cold_store import APP, ColdStore

from vmn_exp.core import index_remote_workers
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_remote_workers import RemoteLoaders

TESTS = os.path.dirname(os.path.abspath(__file__))


class SpawnableStore(ColdStore):
    """A ColdStore a worker process opens again (and counts its reads)."""

    def __init__(self, n, pid=None):
        super().__init__(n)
        self.loads = 0

    def worker_spec(self):
        return ("test_index_remote_workers", "SpawnableStore", (len(self.names),), {})

    def load_file(self, app_name, key, filename):
        self.loads += 1
        return super().load_file(app_name, key, filename)


@pytest.fixture(autouse=True)
def _importable(monkeypatch):
    path = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", TESTS + (os.pathsep + path if path else ""))
    monkeypatch.setattr(index_remote_workers, "worker_count", lambda: 2)


def _work(store, keys):
    return [(key, store._record_files(key), None) for key in keys]


def _in_process(store, key, names):
    record, *flags = refresh_record(key, names, None,
                                    lambda *a: update_record(store, store, APP, *a))
    return record, *flags


def test_workers_load_records_as_the_index_would():
    store = SpawnableStore(300)
    loaders = RemoteLoaders(store.worker_spec(), 2)
    try:
        done = loaders.load(APP, _work(store, store.names))
    finally:
        loaders.close()
    assert set(done) == set(store.names)
    assert store.loads == 0
    for key in store.names[:20]:
        assert done[key] == _in_process(store, key, store._record_files(key))


def test_a_worker_that_cannot_open_the_store_loads_nothing():
    store = SpawnableStore(100)
    loaders = RemoteLoaders(("no_such_module", "Nope", (), {}), 2)
    try:
        assert loaders.load(APP, _work(store, store.names)) == {}
    finally:
        loaders.close()


def test_a_cold_load_reads_its_records_in_workers(tmp_path):
    store = SpawnableStore(10_000)
    index = ExperimentIndex(store, APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=3600)
    index.journaled = True
    index.reconcile()
    try:
        for _ in range(200):
            index.refresh()
            if len(index.published.rows) == 10_000 and index.freshness()["phase"] == "idle":
                break
        assert [r["verstr"] for r in index.rows()] == store.names
        assert store.loads < 10_000 * 2 // 4  # most metadata/run states read elsewhere
    finally:
        index.close()


def test_an_s3_store_says_how_a_worker_opens_it_again(monkeypatch):
    from vmn_exp.storage.s3 import S3SnapshotStorage

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    store = S3SnapshotStorage("bucket", prefix="root/runs", endpoint_url="http://127.0.0.1:9")
    again = index_remote_workers._open(store.worker_spec())
    assert again.cache_identity() == store.cache_identity()
    adapted = S3SnapshotStorage("bucket", prefix="root/runs", client=object())
    assert adapted.worker_spec() is None  # another object store's adapter
