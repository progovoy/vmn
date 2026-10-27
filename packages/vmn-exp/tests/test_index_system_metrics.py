"""``sys_*`` system metrics (sampled on every heartbeat by default) stay off
the index's lean rows, and so off the boards built from them — the
leaderboard rows, facets and sorts — in a side table beside the rows. They are
still served wherever a run's metrics are: row copies (``vmn-exp list``, the
SDK reader), queries (``metrics.sys_rss_mb > 1000`` spots an OOM),
``experiments-columns`` (charts), compare and the run detail page.
"""
import math

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.core.query import filter_rows
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.sdk.reader import list_runs
from vmn_exp.snapshot import LocalSnapshotStorage, open_storage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.ui.readers.diffs import experiment_diff_from_snapshot

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
OOM = "1.0.0-dev.r0001"
QUERY = "metrics.sys_rss_mb > 1000"


def _ts(i, sub=0):
    return f"2026-01-01T00:{i:02d}:{sub:02d}Z"


def _entry(storage, verstr, i, sub, **fields):
    storage.append_log_entry(APP, verstr, "w", {"timestamp": _ts(i, sub), **fields})


def _run(storage, i, rss):
    verstr = f"1.0.0-dev.r{i:04d}"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(i)}, {})
    _entry(storage, verstr, i, 1, type="create", params={"lr": 0.1, "opt": "adam"})
    for step, loss in enumerate((0.9, 0.4 + i / 10)):
        _entry(storage, verstr, i, 2 + step, type="metrics", step=step, values={"loss": loss})
    for beat, mb in enumerate((rss / 2, rss, rss - 1)):
        _entry(storage, verstr, i, 10 + beat, type="metrics",
               values={"sys_rss_mb": mb, "sys_cpu_percent": 50 + beat})
    _entry(storage, verstr, i, 20, type="metrics", values={"sys_gpu_mem_mb": 7})  # once, an int
    return verstr


def _seed(storage):
    return [_run(storage, 0, 500.0), _run(storage, 1, 4000.0), _run(storage, 2, 800.0)]


def _store(tmp_path):
    return open_storage(root=local_store_root(str(tmp_path / "repo")), area="runs")


@pytest.fixture
def served(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = _store(tmp_path)
    _seed(storage)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager))


def _index(tmp_path, name="idx.sqlite"):
    st = LocalSnapshotStorage(str(tmp_path / "local"), area="runs")
    return st, str(tmp_path / name)


def _snap(tmp_path):
    st, db = _index(tmp_path)
    _seed(st)
    index = ExperimentIndex(st, APP, cache_path=db).refresh()
    return st, db, index


def _sys(metrics):
    return {k: v for k, v in metrics.items() if k.startswith("sys_")}


def test_lean_rows_carry_no_system_metrics(tmp_path):
    _, _, index = _snap(tmp_path)
    snap = index.snapshot()
    assert all(not _sys(row["metrics"]) for row in snap.rows)
    assert all(row["metrics"]["loss"] for row in snap.rows)
    index.close()


@pytest.mark.parametrize("restarted", [False, True])
def test_row_copies_carry_them_as_a_direct_listing_does(tmp_path, restarted):
    st, db, index = _snap(tmp_path)
    if restarted:
        index.close()
        index = ExperimentIndex(st, APP, cache_path=db).refresh()
    expected, _ = direct_rows(st, APP)
    copies = index.rows()
    for got, want in zip(copies, expected):
        assert got["metrics"] == want["metrics"]
        assert got["metric_summary"] == want["metric_summary"]
        assert type(got["metrics"]["sys_gpu_mem_mb"]) is int
    assert copies[1]["metric_summary"]["sys_rss_mb"]["max"] == 4000.0
    index.close()


@pytest.mark.parametrize("restarted", [False, True])
def test_queries_read_them(tmp_path, restarted):
    st, db, index = _snap(tmp_path)
    if restarted:
        index.close()
        index = ExperimentIndex(st, APP, cache_path=db).refresh()
    snap = index.snapshot()
    hits = filter_rows(snap.rows, QUERY, extra=lean_extra(snap))
    assert [row["verstr"] for row in hits] == [OOM]
    assert "sys_rss_mb" not in hits[0]["metrics"]  # the shared lean row, untouched
    index.close()


def test_the_reader_lists_and_filters_them(tmp_path):
    storage = _store(tmp_path)
    _seed(storage)
    rows = list_runs(APP, storage=storage, query=QUERY)
    assert [row["verstr"] for row in rows] == [OOM]
    assert rows[0]["metrics"]["sys_rss_mb"] == 3999.0
    assert rows[0]["metric_summary"]["sys_rss_mb"]["max"] == 4000.0


def test_compare_still_diffs_them(tmp_path):
    _, _, index = _snap(tmp_path)
    snap = index.snapshot()
    diff = experiment_diff_from_snapshot(snap, "1.0.0-dev.r0000", OOM)
    assert "sys_rss_mb" in str(diff)
    index.close()


def test_the_board_leaves_them_out(served):
    rows = served.get(f"{BASE}/experiments?limit=10").json()["rows"]
    assert len(rows) == 3 and all(not _sys(row["metrics"]) for row in rows)
    facets = served.get(f"{BASE}/experiments-facets").json()
    assert facets["metric_keys"] == ["loss", "lr"]


def test_the_board_query_finds_the_oom(served):
    body = served.get(f"{BASE}/experiments", params={"q": QUERY, "limit": 10}).json()
    assert [row["verstr"] for row in body["rows"]] == [OOM]


def test_experiments_columns_serve_them(served):
    body = served.get(f"{BASE}/experiments-columns",
                      params={"keys": "metrics.sys_rss_mb,metrics.loss"}).json()
    assert body["columns"]["metrics.sys_rss_mb"] == [499.0, 3999.0, 799.0]
    assert [round(v, 6) for v in body["columns"]["metrics.loss"]] == [0.4, 0.5, 0.6]


def test_run_detail_serves_them_with_their_series(served):
    detail = served.get(f"{BASE}/experiments/{OOM}").json()
    assert detail["metrics"]["sys_rss_mb"] == 3999.0
    assert detail["metric_summary"]["sys_rss_mb"]["max"] == 4000.0
    assert [p["value"] for p in detail["series"]["sys_rss_mb"]] == [2000.0, 4000.0, 3999.0]
    assert not math.isnan(detail["metrics"]["sys_cpu_percent"])
