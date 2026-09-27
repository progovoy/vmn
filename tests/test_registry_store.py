"""Tests for vmn_exp/registry/store.py (C2).

Nine tests covering ensure_model idempotency, sequential version numbers,
list/get APIs, concurrency (local and S3), and abandoned-claim skipping.
"""
import concurrent.futures
import threading

import pytest

from vmn_exp.registry.store import (
    REGISTRY_APP,
    ensure_model,
    get_version,
    list_models,
    list_versions,
    register_version,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_storage(tmp_path):
    from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage

    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _run_ref(app="myapp", verstr="1.0.0"):
    return {"app": app, "verstr": verstr}


# ---------------------------------------------------------------------------
# 1. ensure_model idempotent
# ---------------------------------------------------------------------------


def test_ensure_model_idempotent(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "resnet", description="Image classifier")
    ensure_model(storage, "resnet", description="Updated description")  # must not raise
    models = list_models(storage)
    assert models == ["resnet"]


# ---------------------------------------------------------------------------
# 2. register first version is 1
# ---------------------------------------------------------------------------


def test_register_first_version_is_1(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", _run_ref())
    assert n == 1


# ---------------------------------------------------------------------------
# 3. sequential numbers
# ---------------------------------------------------------------------------


def test_sequential_numbers(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "bert")
    n1 = register_version(storage, "bert", _run_ref())
    n2 = register_version(storage, "bert", _run_ref(verstr="2.0.0"))
    assert n1 == 1
    assert n2 == 2


# ---------------------------------------------------------------------------
# 4. list_versions sorted
# ---------------------------------------------------------------------------


def test_list_versions_sorted(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "vit")
    register_version(storage, "vit", _run_ref(verstr="1.0.0"))
    register_version(storage, "vit", _run_ref(verstr="2.0.0"))
    register_version(storage, "vit", _run_ref(verstr="3.0.0"))
    assert list_versions(storage, "vit") == [1, 2, 3]


# ---------------------------------------------------------------------------
# 5. list_models
# ---------------------------------------------------------------------------


def test_list_models(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "resnet")
    ensure_model(storage, "bert")
    ensure_model(storage, "vit")
    models = list_models(storage)
    assert sorted(models) == ["bert", "resnet", "vit"]


# ---------------------------------------------------------------------------
# 6. get_version returns run ref
# ---------------------------------------------------------------------------


def test_get_version_returns_run_ref(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "resnet")
    ref = _run_ref(app="myapp", verstr="0.5.0")
    register_version(storage, "resnet", ref, description="First deploy")
    meta = get_version(storage, "resnet", 1)
    assert meta is not None
    assert meta["run_ref"]["app"] == "myapp"
    assert meta["run_ref"]["verstr"] == "0.5.0"
    assert meta["description"] == "First deploy"


# ---------------------------------------------------------------------------
# 7. concurrent local: 8 threads → {1..8}
# ---------------------------------------------------------------------------


def test_concurrent_register_distinct_numbers_local(tmp_path):
    storage = _local_storage(tmp_path)
    ensure_model(storage, "model_c")

    results = []
    errors = []
    barrier = threading.Barrier(8, timeout=10)

    def worker():
        try:
            barrier.wait()
            n = register_version(storage, "model_c", _run_ref())
            results.append(n)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(worker) for _ in range(8)]
        for fut in futs:
            fut.result(timeout=15)

    assert not errors, errors
    assert sorted(results) == list(range(1, 9))


# ---------------------------------------------------------------------------
# 8. concurrent S3: two storages on one moto bucket → distinct numbers
# ---------------------------------------------------------------------------


moto = pytest.importorskip("moto")


@pytest.fixture()
def s3_env(monkeypatch):
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket="vmn-test")
        yield


def _s3_storage():
    from version_stamp.cli.snapshot_storage_s3 import S3SnapshotStorage

    return S3SnapshotStorage("vmn-test", prefix="reg")


def test_concurrent_register_two_cached_hosts_s3(s3_env):
    storage_a = _s3_storage()
    storage_b = _s3_storage()

    ensure_model(storage_a, "s3model")

    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker(storage):
        try:
            barrier.wait()
            n = register_version(storage, "s3model", _run_ref())
            results.append(n)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(storage_a,))
    t2 = threading.Thread(target=worker, args=(storage_b,))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, errors
    assert sorted(results) == [1, 2]


# ---------------------------------------------------------------------------
# 9. abandoned S3 claim is skipped
# ---------------------------------------------------------------------------


def test_abandoned_s3_claim_is_skipped(s3_env):
    import boto3

    storage = _s3_storage()

    ensure_model(storage, "abandoned_model")

    # Manually plant an abandoned claim for version 1: put .claim but not metadata.yml
    # S3 key format: {prefix}/{app_key}/{safe_verstr}/{CLAIM_FILE}
    # app_key for "vmn-registry" is "vmn-registry"; safe_verstr("abandoned_model.v1") = "abandoned_model.v1"
    claim_key = "reg/vmn-registry/abandoned_model.v1/.claim"
    boto3.client("s3").put_object(Bucket="vmn-test", Key=claim_key, Body=b"")

    # register_version should skip v1 (abandoned) and return 2
    n = register_version(storage, "abandoned_model", _run_ref())
    assert n == 2

    # v1 should not appear in list_versions (no metadata)
    assert list_versions(storage, "abandoned_model") == [2]
