"""The index folds an S3 run's metric objects as its listing found them:
listing ``metrics/`` again per record was a fourth LIST per run on a cold
load (~0.8 ms of botocore CPU each, 100k LISTs at 100k runs)."""
import os

import pytest
from s3_helpers import meta, mocked_bucket, record_calls, s3_storage

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns

APP = "app"
T0 = 1_767_225_600_000_001


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        for v in ("1.0.0-dev.a", "1.0.0-dev.b"):
            storage.save(APP, v, meta(v), {})
            storage.save_file(APP, v, "run_state.yml", "state: finished\nexit_code: 0\n")
            for seq in (1, 2):
                storage.put_metric_segment(APP, v, "w~o1", seq, encode_block(
                    {"loss": Columns([seq], [T0 + seq], [1.0 / seq])}))
        yield storage


def test_a_load_lists_no_metrics_folder_its_listing_covered(s3, tmp_path):
    storage = s3_storage()
    calls = record_calls(storage._s3)
    index = ExperimentIndex(storage, APP, os.path.join(tmp_path, "i.sqlite"), full_sweep_sec=0)

    rows = index.refresh().rows()

    assert [r["metrics"]["loss"] for r in rows] == [0.5, 0.5]
    listed = [p["Prefix"] for op, p in calls if op == "ListObjectsV2"]
    assert not [p for p in listed if p.endswith("/metrics/") and "Delimiter" not in p], listed
    metric_lists = [p for op, p in calls if op == "ListObjectsV2"
                    and p["Prefix"].endswith("/metrics/")]
    assert len(metric_lists) <= 2  # the listing's own, one per record at most
