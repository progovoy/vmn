"""Zoom ranges and paged metric keys over the UI API (plan 12 §7, phase 3a).

A zoom asks one run's series for ``step_min..step_max``; over a compacted
writer that reads the footer, one LOD slice and the raw chunks at the range's
edges — never the whole file.
"""
import os
import random
import tempfile

import pytest

pytest.importorskip("fastapi")

from test_fix_ui_perf_series import APP, BASE, _client, _run

from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.storage.local import LocalSnapshotStorage

V = "1.0.0-dev.a"
N = 600_000
T0 = 1_700_000_000_000_000


def _compacted(storage, verstr, n=N, keys=("loss",)):
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    rng = random.Random(3)
    steps = list(range(n))
    cols = {k: Columns(steps, [T0 + i * 1000 for i in steps], [rng.random() for _ in steps])
            for k in keys}
    fd, path = tempfile.mkstemp(suffix=".vmx")
    with os.fdopen(fd, "wb") as f:
        f.write(build_index("w", cols))
    try:
        assert storage.put_indexed(APP, verstr, "w", path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    client, storage = _client(tmp_path_factory.mktemp("big"))
    _compacted(storage, V)
    return client, storage


@pytest.fixture
def reads(monkeypatch):
    seen = []
    original = LocalSnapshotStorage.read_range

    def spy(self, app_name, verstr, name, offset, length):
        seen.append(length)
        return original(self, app_name, verstr, name, offset, length)

    monkeypatch.setattr(LocalSnapshotStorage, "read_range", spy)
    return seen


def _file_size(storage):
    [(_, size)] = storage.metric_objects(APP, V)["w"]
    return size


def test_reader_thins_a_compacted_range_from_a_bounded_read(big, reads):
    _, storage = big
    reader = SeriesReader.from_storage(storage, APP, V, rewinds=())
    points = reader.thinned("loss", 1000, step_range=(100_000, 300_000))
    assert points[0]["step"] == 100_000 and points[-1]["step"] == 300_000
    assert all(100_000 <= p["step"] <= 300_000 for p in points)
    assert 500 <= len(points) <= 1010
    assert isinstance(points[0]["ts"], str)
    assert sum(reads) < _file_size(storage) / 3


def test_batch_series_reads_a_step_range_boundedly(big, reads):
    client, storage = big
    body = {"verstrs": [V], "keys": ["loss"], "max_points": 1000,
            "step_min": 100_000, "step_max": 300_000}
    r = client.post(f"{BASE}/series", json=body)
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == {"series", "series_total", "step_metrics", "missing"}
    points = payload["series"][V]["loss"]
    assert points[0]["step"] == 100_000 and points[-1]["step"] == 300_000
    assert set(points[0]) == {"step", "ts", "value"}
    assert payload["series_total"][V] == {"loss": N}
    assert sum(reads) < _file_size(storage) / 3


def test_metric_keys_read_only_the_footer(big, reads):
    client, storage = big
    body = client.get(f"{BASE}/experiments/{V}/metric-keys").json()
    assert body["keys"] == [{"name": "loss", "count": N}]
    assert sum(reads) < _file_size(storage) / 20


@pytest.fixture
def ws(tmp_path):
    return _client(tmp_path)


def test_detail_series_keep_a_step_range(ws):
    client, storage = ws
    _run(storage, V, n=10)
    detail = client.get(f"{BASE}/experiments/{V}?keys=loss&step_min=3&step_max=5").json()
    assert [p["step"] for p in detail["series"]["loss"]] == [3, 4, 5]
    assert detail["series_total"] == {"loss": 10}
    assert set(detail["metrics"]) == {"loss", "acc"}


def test_detail_open_ended_ranges(ws):
    client, storage = ws
    _run(storage, V, n=10)
    detail = client.get(f"{BASE}/experiments/{V}?keys=loss&step_min=7").json()
    assert [p["step"] for p in detail["series"]["loss"]] == [7, 8, 9]
    detail = client.get(f"{BASE}/experiments/{V}?keys=loss&step_max=1").json()
    assert [p["step"] for p in detail["series"]["loss"]] == [0, 1]


def test_batch_series_range_over_a_jsonl_run(ws):
    client, storage = ws
    _run(storage, V, n=10)
    body = {"verstrs": [V, "1.0.0-dev.zz"], "keys": None, "step_min": 2, "step_max": 4}
    payload = client.post(f"{BASE}/series", json=body).json()
    assert [p["step"] for p in payload["series"][V]["acc"]] == [2, 3, 4]
    assert payload["missing"] == ["1.0.0-dev.zz"]


def test_batch_series_rejects_bad_ranges(ws):
    client, storage = ws
    _run(storage, V, n=3)
    for bad in ({"step_min": "a"}, {"step_max": True}, {"step_min": 1, "x": "acc"}):
        r = client.post(f"{BASE}/series", json={"verstrs": [V], **bad})
        assert r.status_code == 400, bad


def test_metric_keys_page_and_filter_by_prefix(ws):
    client, storage = ws
    _run(storage, V, n=3, keys=[f"train/m{i:02d}" for i in range(30)] + ["val/loss"])
    url = f"{BASE}/experiments/{V}/metric-keys"
    first = client.get(f"{url}?limit=10").json()
    assert first["total"] == 31 and first["offset"] == 0 and first["limit"] == 10
    assert [k["name"] for k in first["keys"]] == [f"train/m{i:02d}" for i in range(10)]
    assert first["keys"][0]["count"] == 3
    rest = client.get(f"{url}?offset=30&limit=10").json()
    assert [k["name"] for k in rest["keys"]] == ["val/loss"]
    val = client.get(f"{url}?prefix=val/").json()
    assert val["total"] == 1 and [k["name"] for k in val["keys"]] == ["val/loss"]


def test_metric_keys_of_a_missing_run_is_404(ws):
    client, _ = ws
    assert client.get(f"{BASE}/experiments/1.0.0-dev.zz/metric-keys").status_code == 404


def test_detail_says_whether_the_run_is_compacted(big):
    client, _ = big
    assert client.get(f"{BASE}/experiments/{V}?series=0").json()["compacted"] is True
