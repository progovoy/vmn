"""Scale guard: a cold index loads a production-shaped S3 store (the s3bench
seed, 30 ms a request) at a sustained rate, not the ~120 runs/s that made a
497k-run store take hours (three LISTs a record listed before the first
publish, per-chunk renumbering and snapshot copies quadratic in the runs).
Timed, so serial."""
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
from uiload import s3bench, s3bench_seed  # noqa: E402
from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.storage.registry import open_store  # noqa: E402

PARAMS = {"runs": 6000, "stuck": 60, "segments": 30, "seed": 0}
LATENCY_MS = 30
FIRST_PUBLISH_SEC = 15.0
RUNS_PER_SEC = 200  # sustained, first publish to loaded
LIMIT_SEC = 300


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    for key, value in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x",
                       "AWS_DEFAULT_REGION": "us-east-1",
                       "AWS_EC2_METADATA_DISABLED": "true"}.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _quiet_botocore():
    """The suite logs at DEBUG; botocore's debug lines cost more CPU than
    the requests (a server logs at INFO)."""
    logger = logging.getLogger("botocore")
    level = logger.level
    logger.setLevel(logging.INFO)
    yield
    logger.setLevel(level)


@pytest.fixture(scope="module")
def endpoint(tmp_path_factory):
    data = str(tmp_path_factory.mktemp("cold_load_bench"))
    s3bench_seed.seed(data, PARAMS, time.time())
    proc, url, _ = s3bench.start_moto(data, LATENCY_MS, data, fast=True)
    yield url
    proc.terminate()
    proc.wait(10)


def _load(index):
    """``(seconds to the first non-empty publish, seconds to loaded)``."""
    started, first, done = time.monotonic(), [], threading.Event()

    def watch():
        while not done.is_set():
            snap = index.published
            if snap is not None and snap.rows:
                first.append(time.monotonic() - started)
                return
            time.sleep(0.05)

    threading.Thread(target=watch, daemon=True).start()
    try:
        while time.monotonic() - started < LIMIT_SEC:
            index.refresh()
            snap = index.published
            if snap is not None and len(snap.rows) == PARAMS["runs"] and not snap.loading:
                break
    finally:
        done.set()
    return (first or [None])[0], time.monotonic() - started


@pytest.mark.serial
def test_a_cold_index_loads_a_remote_store_at_a_sustained_rate(endpoint, tmp_path):
    storage = open_store(f"s3://{s3bench.BUCKET}/{s3bench.ROOT}?endpoint_url={endpoint}")
    index = ExperimentIndex(storage, s3bench_seed.APP, str(tmp_path / "idx.sqlite"))
    index.journaled = True
    index.reconcile()
    try:
        first, loaded = _load(index)
    finally:
        index.close()
    rate = PARAMS["runs"] / (loaded - (first or 0))
    print(f"\n{PARAMS['runs']} runs at {LATENCY_MS} ms: first publish {first}s, "
          f"loaded {loaded:.1f}s, {rate:.0f} runs/s")
    assert len(index.published.rows) == PARAMS["runs"]
    assert first is not None and first <= FIRST_PUBLISH_SEC
    assert rate >= RUNS_PER_SEC
