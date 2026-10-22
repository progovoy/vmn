"""A cold remote load reads newest records first, but an outer run is created
before its inner runs — so it would load last, and the Outer runs board stay
empty until the whole index had loaded. A loaded record's unloaded parent (and
its parent, up the chain) is read next, ahead of the rest of the queue."""
import threading
import time

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
ROOT, MIDDLE = "0.0.0", "0.0.1"


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


def _parent(i):
    return None if i == 0 else ROOT if i == 1 else MIDDLE


def _seed(storage):
    for i in range(N):
        v = f"0.0.{i}"
        meta = {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
        if _parent(i):
            meta["parent"] = _parent(i)
        storage.save(APP, v, meta, {})
        storage.save_file(APP, v, "run_state.yml", "state: succeeded\nexit_code: 0\n")


def _dated_by_verstr(storage):
    """List each record's metadata.yml as written at its verstr's last number."""
    list_files = storage.list_files

    def dated(app_name, keys=None, **kw):
        listing = list_files(app_name, keys=keys, **kw)
        for verstr, files in listing.items():
            size, _, etag = files["metadata.yml"]
            files["metadata.yml"] = (size, float(verstr.rsplit(".", 1)[1]), etag)
        return listing

    storage.list_files = dated


def _hold_metadata_loads_past(storage, n_free, release):
    load, lock, count = storage.load_file, threading.Lock(), [0]

    def load_file(app_name, verstr, filename):
        if filename == "metadata.yml":
            with lock:
                count[0] += 1
                n = count[0]
            if n > n_free:
                release.wait(10)
        return load(app_name, verstr, filename)

    storage.load_file = load_file


def _rows_once(index, n, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = index.snapshot().rows
        if len(rows) >= n:
            return rows
        time.sleep(0.01)
    raise AssertionError(f"never saw {n} rows")


def test_a_cold_load_reads_loaded_runs_ancestors_next(s3, tmp_path):
    _seed(_storage())
    storage, release = _storage(), threading.Event()
    _dated_by_verstr(storage)
    _hold_metadata_loads_past(storage, CHUNK + 2, release)
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))
    try:
        rows = _rows_once(index, CHUNK + 2)
    finally:
        release.set()
    index.wait_revalidated(10)

    assert {ROOT, MIDDLE} <= {r["verstr"] for r in rows}
    assert len(index.snapshot().rows) == N
