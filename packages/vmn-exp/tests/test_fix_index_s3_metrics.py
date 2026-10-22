"""Columnar metric files (``metrics/*.vms``/``.vmx``) are part of an S3
record's listed files, as they are of a local one, so the index folds them
into the rows (the leaderboard's metrics, an outer run's best)."""
import os

import pytest

moto = pytest.importorskip("moto")
import boto3  # noqa: E402

from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.core.metric_block import encode_block  # noqa: E402
from vmn_exp.core.metric_columns import Columns  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "myapp"
BUCKET = "vmn-bucket"
V = "0.0.1"


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        storage = S3SnapshotStorage(BUCKET, prefix="exps")
        storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
        storage.save_file(APP, V, "run_state.yml", "state: running\nexit_code: null\n")
        yield storage


def _segment(storage, seq, step, loss):
    block = encode_block({"loss": Columns([step], [1_700_000_000_000_000 + step], [loss])})
    storage.put_metric_segment(APP, V, "w0", seq, block)


def test_a_full_listing_carries_the_metric_files(storage):
    _segment(storage, 0, 1, 0.5)
    assert "metrics/w0.vms" in storage.list_files(APP)[V]


def test_a_keyed_listing_carries_the_metric_files(storage):
    _segment(storage, 0, 1, 0.5)
    assert "metrics/w0.vms" in storage.list_files(APP, keys=[V])[V]


def test_the_index_folds_s3_metric_segments_as_they_arrive(storage, tmp_path):
    _segment(storage, 0, 1, 0.5)
    index = ExperimentIndex(storage, APP, os.path.join(tmp_path, "i.sqlite"), full_sweep_sec=0)
    assert index.refresh().snapshot().rows[0]["metrics"] == {"loss": 0.5}

    _segment(storage, 1, 2, 0.25)
    assert index.refresh().snapshot().rows[0]["metrics"] == {"loss": 0.25}
