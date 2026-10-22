"""A cold index over a large remote store publishes and persists as it goes:
the dashboard answers after the first chunk of records instead of after
every record's GETs, and a load cut short resumes where it stopped."""
import threading

import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

import vmn_exp.core.index as index_module  # noqa: E402
from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "myapp"
BUCKET = "vmn-bucket"
CHUNK = 5
N = 12


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", CHUNK)
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def _storage():
    return S3SnapshotStorage(BUCKET, prefix="exps")


def _seed(storage):
    for i in range(N):
        v = f"0.0.{i}"
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
        storage.save_file(APP, v, "run_state.yml", "state: succeeded\nexit_code: 0\n")


def _metadata_loads(storage, on_load):
    """Call ``on_load(n)`` before the n-th ``metadata.yml`` load of *storage*."""
    load, lock, count = storage.load_file, threading.Lock(), [0]

    def load_file(app_name, verstr, filename):
        if filename == "metadata.yml":
            with lock:
                count[0] += 1
                n = count[0]
            on_load(n)
        return load(app_name, verstr, filename)

    storage.load_file = load_file
    return count


def test_a_cold_load_answers_after_its_first_chunk(s3, tmp_path):
    _seed(_storage())
    storage, release = _storage(), threading.Event()
    _metadata_loads(storage, lambda n: n > CHUNK and release.wait(10))
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))

    first = index.snapshot()
    release.set()
    index.wait_revalidated(10)

    assert len(first.rows) == CHUNK
    assert len(index.snapshot().rows) == N


def test_a_cold_load_cut_short_keeps_what_it_read(s3, tmp_path):
    _seed(_storage())
    cache = str(tmp_path / "i.sqlite")
    broken = _storage()

    def fail_past_first_chunk(n):
        if n > CHUNK:
            raise OSError("connection reset")

    _metadata_loads(broken, fail_past_first_chunk)
    with pytest.raises(OSError):
        ExperimentIndex(broken, APP, cache).refresh()

    storage = _storage()
    loads = _metadata_loads(storage, lambda n: None)
    rows = ExperimentIndex(storage, APP, cache).refresh().snapshot().rows

    assert len(rows) == N
    assert loads[0] == N - CHUNK


def test_the_s3_client_pools_a_connection_per_index_reader(s3):
    pool = _storage()._s3.meta.config.max_pool_connections
    assert pool >= index_module._REMOTE_WORKERS
