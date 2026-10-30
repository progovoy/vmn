"""The free-threaded GC policy (plan 26 F5) runs with automatic collection
off and collects on a clock that stretches to an hour while collections
find little. That is safe only while serving index generations makes no
cyclic garbage: each generation's old snapshot must be freed by reference
counting, not wait up to an hour for the collector. The S3 storage path and
an HTTP board poll make a few dozen cyclic objects each (botocore, the test
client), far below what shortens the clock (``MUCH_GARBAGE``)."""
import gc

import pytest
from leaderboard_fleet import T0
from test_ui_generation_memory import SCHEMA, _fleet, _serve, _snapshot
from s3_helpers import mocked_bucket, s3_storage
from test_fix_ui_list_serving import BASE, _app, _run
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod
from vmn_exp.snapshot import LocalSnapshotStorage

PER_S3_REFRESH = 100
PER_HTTP_POLL = 50


@pytest.fixture(autouse=True)
def _collector_off(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    was = gc.isenabled()
    gc.disable()
    yield
    (gc.enable if was else gc.disable)()


def _publish(fleet, cache):
    snap = _snapshot(fleet)
    view = snap.summarized(SCHEMA)
    _serve(cache, view)
    fleet.mutate(T0, 5, reparent=False)


def test_serving_a_generation_makes_no_cyclic_garbage():
    fleet, cache = _fleet(), LeaderboardCache()
    _publish(fleet, cache)
    gc.collect()
    garbage = []
    for _ in range(20):
        _publish(fleet, cache)
        garbage.append(gc.collect())
    assert garbage == [0] * 20


def test_an_index_refresh_makes_no_cyclic_garbage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")

    def add(i):
        verstr = f"0.0.1-dev.abc.r{i}"
        st.save("app", verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})

    for i in range(200):
        add(i)
    index = ExperimentIndex(st, "app", cache_path=str(tmp_path / "idx.sqlite"))
    index.refresh()
    gc.collect()
    garbage = []
    try:
        for i in range(10):
            add(1000 + i)
            index.refresh()
            index.snapshot().summarized(SCHEMA)
            garbage.append(gc.collect())
    finally:
        index.close()
    assert garbage == [0] * 10


def _refreshes(st, index, add, n):
    garbage = []
    for i in range(n):
        add(st, 1000 + i)
        index.refresh()
        index.snapshot()
        garbage.append(gc.collect())
    return garbage


def _save_s3(st, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    st.save("app", verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    st.append_log_entry("app", verstr, "w0", {"timestamp": "2026-01-01T00:01:00Z",
                                              "type": "metrics", "values": {"loss": 1.0}})


def test_an_s3_index_refresh_makes_little_cyclic_garbage(monkeypatch, tmp_path):
    with mocked_bucket(monkeypatch):
        st = s3_storage()
        for i in range(100):
            _save_s3(st, i)
        index = ExperimentIndex(st, "app", cache_path=str(tmp_path / "idx.sqlite"), full_sweep_sec=0)
        index.refresh()
        gc.collect()
        try:
            garbage = _refreshes(st, index, _save_s3, 10)
        finally:
            index.close()
    assert max(garbage) < PER_S3_REFRESH, garbage


def test_an_http_board_poll_makes_little_cyclic_garbage(tmp_path):
    from fastapi.testclient import TestClient

    app, storage = _app(tmp_path)
    for i in range(300):
        _run(storage, i, loss=i * 0.1, lr=i)
    client = TestClient(app)
    routes = [f"{BASE}/experiments?limit=50", f"{BASE}/experiments-status",
              f"{BASE}/experiments-facets", f"{BASE}/experiments-baselines"]
    for route in routes:
        client.get(route)
    gc.collect()
    garbage = []
    for route in routes * 5:
        assert client.get(route).status_code == 200
        garbage.append(gc.collect())
    assert max(garbage) < PER_HTTP_POLL, garbage
