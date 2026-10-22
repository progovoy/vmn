"""uiload s3bench: the seeded store's shape, its determinism, the fake S3's
sorted listing, and that vmn's own S3 reader reads the seeded records."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402
from uiload import s3bench_moto, s3bench_seed  # noqa: E402
from vmn_exp.sdk.reader import list_runs  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

PARAMS = {"runs": 80, "stuck": 6, "segments": 4, "seed": 0}
NOW = 1_790_000_000.0


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    for key, value in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x",
                       "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(key, value)


def test_layout_has_three_outer_runs_and_a_fifth_singles():
    roles = s3bench_seed.layout(2000)
    outers = [i for i, (kind, _) in enumerate(roles) if kind == "outer"]
    sizes = [sum(1 for _, parent in roles if parent == i) for i in outers]
    assert sizes == [15, 1000, 2000 - 3 - 400 - 1015]
    assert sum(kind == "single" for kind, _ in roles) == 400


def test_seed_is_deterministic(tmp_path):
    a = s3bench_seed.seed(str(tmp_path / "a"), PARAMS, NOW, workers=1)
    b = s3bench_seed.seed(str(tmp_path / "b"), PARAMS, NOW, workers=1)
    assert a == b
    assert list(s3bench_seed.iter_objects(str(tmp_path / "a"))) == \
        list(s3bench_seed.iter_objects(str(tmp_path / "b")))
    assert s3bench_seed.load_manifest(str(tmp_path / "a"), PARAMS) == a
    assert s3bench_seed.load_manifest(str(tmp_path / "a"), dict(PARAMS, runs=81)) is None


def _pages(s3, **kwargs):
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket="bkt1", PaginationConfig={"PageSize": 2}, **kwargs)
    return [([o["Key"] for o in p.get("Contents", [])],
             [c["Prefix"] for c in p.get("CommonPrefixes", [])]) for p in pages]


@mock_aws
def test_sorted_listing_matches_moto():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="bkt1")
    for key in ("a/1/x", "a/1/y", "a/2/x", "a/10/z", "a/2b", "a/3", "b/1", "a0"):
        s3.put_object(Bucket="bkt1", Key=key, Body=b"")
    cases = [{"Prefix": "a/", "Delimiter": "/"}, {"Prefix": "a/"}, {"Delimiter": "/"},
             {"Prefix": "a/1", "Delimiter": "/"}, {"Prefix": "zz"}, {"StartAfter": "a/10/z"}]
    moto = [_pages(s3, **case) for case in cases]
    undo = s3bench_moto.install()
    try:
        assert [_pages(s3, **case) for case in cases] == moto
        listed = s3.list_objects(Bucket="bkt1", Prefix="a/", Delimiter="/")
        assert [o["Key"] for o in listed["Contents"]] == ["a/2b", "a/3"]
        assert [c["Prefix"] for c in listed["CommonPrefixes"]] == ["a/1/", "a/10/", "a/2/"]
    finally:
        undo()


@mock_aws
def test_vmn_reads_the_seeded_store(tmp_path):
    undo = s3bench_moto.install()
    try:
        _read_seeded_store(tmp_path)
    finally:
        undo()


def _read_seeded_store(tmp_path):
    manifest = s3bench_seed.seed(str(tmp_path), PARAMS, NOW, workers=1)
    assert s3bench_moto.load(str(tmp_path), "bench", "vmn-exp") == manifest["objects"]
    storage = open_storage("s3://bench/vmn-exp", area=RUNS, writer=False)
    rows = list_runs(manifest["app"], storage=storage, use_index=False, include_archived=True)
    assert len(rows) == PARAMS["runs"]
    by_status = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row["verstr"])
    assert sorted(by_status["stuck"]) == sorted(manifest["stuck"])
    finished = [r for r in rows if r["status"] == "succeeded" and r["kind"] != "outer"]
    assert sum(r["kind"] == "outer" for r in rows) == 3
    stuck = [r for r in rows if r["status"] == "stuck"]
    assert all("sharpe" in r["metrics"] for r in finished + stuck)
