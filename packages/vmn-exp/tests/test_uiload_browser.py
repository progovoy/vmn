"""uiload browser checks against a real `vmn-exp ui` server (in-process uvicorn)
over a small seeded root: every check returns sane numbers, charts paint, the
query box filters, scrolling reaches deep rows, status counts match the seed."""
import datetime
import json
import os
import time

import pytest
import yaml

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")

from uiload.browser import BROWSER_BUDGETS, BrowserChecks, evaluate  # noqa: E402
from uiload.inproc_server import serve_root  # noqa: E402

APP = "loadapp"
WS = "ws"
RUNS = 300
STEPS = 300
# Status of seeded run i by i % 10.
STATUS_OF = {0: "running", 1: "failed", 2: "stuck"}
WIDE_RUN = 13
EXPECTED = {"running": 30, "failed": 30, "stuck": 30, "succeeded": 210, "created": 0}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _run_state(status, now):
    if status == "running":
        return {"state": "running", "heartbeat": _iso(now), "heartbeat_interval_sec": 30,
                "started_at": _iso(now)}
    if status == "stuck":
        old = now - datetime.timedelta(hours=1)
        return {"state": "running", "heartbeat": _iso(old), "heartbeat_interval_sec": 1,
                "started_at": _iso(old)}
    return {"state": "finished", "exit_code": 1 if status == "failed" else 0, "duration_sec": 5}


def _write_log(path, i, steps, now):
    with open(path, "w") as f:
        for s in range(steps):
            values = {"loss": 1.0 / (s + 1) + i * 1e-4, "acc": s / steps}
            f.write(json.dumps({"timestamp": _iso(now), "type": "metrics", "step": s,
                                "values": values}) + "\n")


def _seed(root):
    base = os.path.join(root, ".vmn", "store", "runs", APP)
    now = datetime.datetime.now(datetime.timezone.utc)
    stale = time.time() - 3600
    for i in range(RUNS):
        verstr = f"0.0.1-dev.abc1234.def5678.r{i}"
        folder = os.path.join(base, verstr)
        os.makedirs(folder)
        ts = now - datetime.timedelta(seconds=RUNS - i)
        meta = {"verstr": verstr, "name": f"hist-{i:06d}", "timestamp": _iso(ts),
                "params": {"lr": 0.001 * (i % 7), "seed": i}}
        with open(os.path.join(folder, "metadata.yml"), "w") as f:
            yaml.dump(meta, f)
        _write_log(os.path.join(folder, "log.w.jsonl"), i, STEPS if i < 20 else 5, now)
        if i == WIDE_RUN:  # enough params to push the charts below the fold
            with open(os.path.join(folder, "log.w.jsonl"), "a") as f:
                wide = {f"hp_{k:03d}": k * 0.01 for k in range(60)}
                f.write(json.dumps({"timestamp": _iso(now), "type": "create", "params": wide}) + "\n")
        status = STATUS_OF.get(i % 10, "succeeded")
        state_path = os.path.join(folder, "run_state.yml")
        with open(state_path, "w") as f:
            yaml.dump(_run_state(status, now), f)
        if status == "stuck":
            os.utime(state_path, (stale, stale))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("uiload_browser")
    root = tmp / "root"
    (root / ".git").mkdir(parents=True)
    _seed(str(root))
    with serve_root(root, tmp / "data", WS) as (base_url, _):
        yield base_url


@pytest.fixture(scope="module")
def checks(server):
    from playwright.sync_api import Error

    try:
        bc = BrowserChecks(server, WS, APP).__enter__()
    except Error as exc:  # chromium not installed
        pytest.skip(f"chromium unavailable: {exc}")
    yield bc
    bc.__exit__(None, None, None)


def test_leaderboard_first_rows(checks):
    ms = checks.leaderboard_first_rows_ms()
    assert 0 < ms < 15000


def test_scroll_reaches_deep_rows(checks):
    out = checks.scroll_jank(duration_sec=2)
    assert out["rows_seen"] >= RUNS - 10
    assert out["longtasks_n"] >= 0
    assert out["max_longtask_ms"] >= 0


def test_run_detail_chart_paints(checks):
    ms = checks.run_detail_chart_ms("hist-000007")
    assert 0 < ms < 15000


def test_run_detail_chart_below_the_fold_paints(checks):
    ms = checks.run_detail_chart_ms(f"hist-{WIDE_RUN:06d}")
    assert 0 < ms < 15000


def test_query_filters_rows(checks):
    ms, count = checks.query_filter_ms('name = "hist-000010"')
    assert 0 < ms < 15000
    assert count == 1
    _, failed = checks.query_filter_ms('status = "failed"')
    assert failed == EXPECTED["failed"]


def test_status_counts_match_seed(checks):
    counts = checks.status_pill_counts()
    assert counts["totals"] == EXPECTED
    assert sum(counts["visible"].values()) > 0
    assert set(counts["visible"]) <= set(EXPECTED)


def test_idle_memory_is_sampled(checks):
    out = checks.idle_memory_growth(duration_sec=3)
    assert out["samples"] >= 2
    assert out["start_mb"] > 0 and out["end_mb"] > 0
    assert out["growth_mb"] == pytest.approx(out["end_mb"] - out["start_mb"])


def test_no_console_errors(checks):
    assert checks.console_errors() == []


def test_run_all_returns_every_metric(checks):
    results = checks.run_all(run_name="hist-000003", query='status = "stuck"',
                             scroll_sec=1, idle_sec=2)
    for key in ("first_rows_ms", "longtasks_n", "max_longtask_ms", "rows_seen", "chart_ms",
                "query_ms", "query_rows", "idle_growth_mb", "status_counts", "console_errors"):
        assert key in results, key
    assert results["query_rows"] == EXPECTED["stuck"]


def test_evaluate_flags_only_budget_breaches():
    good = {"first_rows_ms": 100, "max_longtask_ms": 50, "chart_ms": 200, "query_ms": 400,
            "idle_growth_mb": 1.0, "console_errors": []}
    assert evaluate(good, "smoke") == []
    bad = dict(good, first_rows_ms=2500, chart_ms=9000, console_errors=["boom"])
    problems = evaluate(bad, "smoke")
    assert len(problems) == 3
    assert any("first_rows_ms" in p for p in problems)
    assert any("console" in p for p in problems)
    assert evaluate(dict(good, first_rows_ms=2500), "load") == []
    assert BROWSER_BUDGETS["smoke"]["first_rows_ms"] == 2000
    assert BROWSER_BUDGETS["load"]["first_rows_ms"] == 3000
