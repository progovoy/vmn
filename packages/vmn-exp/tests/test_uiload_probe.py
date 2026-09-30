"""The uiload HTTP prober against a real ``vmn-exp ui`` app served by uvicorn
over a small seeded store with a couple of live (heartbeating) runs."""
import datetime
import json
import os
import threading
import time

import pytest
import yaml

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")

from uiload import probe as probe_mod  # noqa: E402
from uiload.inproc_server import serve_root  # noqa: E402
from uiload.probe import Probe, by_name, fetch_all_rows, status_counts  # noqa: E402

APP = "loadapp"
EXPECTED = {"succeeded": 20, "failed": 8, "created": 4, "running": 2}
LIVE_NAMES = ("live-000000", "live-000001")


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()


def _write(folder, name, data):
    with open(os.path.join(folder, name), "w") as f:
        f.write(data)


def _append_metrics(folder, step, values):
    entry = {"timestamp": _iso(time.time()), "type": "metrics", "step": step, "values": values}
    with open(os.path.join(folder, "log.w.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def _running_state(started):
    now = _iso(time.time())
    return yaml.dump({"state": "running", "started_at": started, "heartbeat": now,
                      "heartbeat_interval_sec": 1})


def _seed(root):
    base = os.path.join(root, ".vmn", APP, "experiments")
    folders, i = {}, 0
    for status, n in EXPECTED.items():
        for _ in range(n):
            live = status == "running"
            name = LIVE_NAMES[len(folders)] if live else f"hist-{i:06d}"
            verstr = f"0.0.1-dev.abc1234.def5678.r{i}"
            folder = os.path.join(base, verstr)
            os.makedirs(folder)
            meta = {"verstr": verstr, "name": name, "timestamp": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z"}
            _write(folder, "metadata.yml", yaml.dump(meta))
            params = {"type": "params", "timestamp": _iso(time.time()), "params": {"lr": 0.001 * (i + 1), "opt": "adam"}}
            _write(folder, "log.w.jsonl", json.dumps(params) + "\n")
            for step in range(5):
                _append_metrics(folder, step, {"loss": 1.0 / (i + step + 1), "acc": 0.1 * step, "probe_ts": time.time()})
            if live:
                folders[name] = folder
                _write(folder, "run_state.yml", _running_state(_iso(time.time())))
            elif status != "created":
                code = 0 if status == "succeeded" else 1
                _write(folder, "run_state.yml", yaml.dump({"state": "finished", "exit_code": code}))
            i += 1
    return folders


def _keep_alive(folders, stop):
    started = _iso(time.time())
    step = 5
    while not stop.wait(0.3):
        for folder in folders.values():
            _append_metrics(folder, step, {"loss": 0.01, "probe_ts": time.time()})
            _write(folder, "run_state.yml", _running_state(started))
        step += 1


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("uiload")
    root = tmp / "repo"
    (root / ".git").mkdir(parents=True)
    live = _seed(str(root))
    stop = threading.Event()
    beater = threading.Thread(target=_keep_alive, args=(live, stop), daemon=True)
    beater.start()
    with serve_root(root, tmp / "data", "ws") as served:
        yield served
    stop.set()


def test_discover_finds_workspace_and_app(server):
    base, ws = server
    assert Probe(base, None, None).discover() == (ws, APP)


def test_run_exercises_every_route_without_errors(server):
    base, ws = server
    seen = []
    report = Probe(base, ws, APP).run(duration_sec=4, concurrency=4, on_sample=seen.append)

    assert seen, "on_sample was never called"
    assert report.errors == 0, report.to_dict()
    for route in probe_mod.ROUTES:
        stats = report.routes[route]
        assert stats["count"] > 0, route
        assert stats["errors"] == 0, route
        assert 0 < stats["p50"] <= stats["p95"] <= stats["p99"] <= stats["max"], route
    assert report.conditional > 0
    assert report.not_modified > 0
    assert 0 < report.rate_304 <= 1


def test_run_measures_freshness_of_live_rows(server):
    base, ws = server
    report = Probe(base, ws, APP).run(duration_sec=3, concurrency=2, freshness_interval=0.2)

    assert report.freshness["count"] > 0
    assert report.freshness["p95"] < 5
    assert report.freshness["max"] >= report.freshness["p50"] >= 0


def test_report_is_json_serialisable(server):
    base, ws = server
    report = Probe(base, ws, APP).run(duration_sec=1, concurrency=2)
    data = json.loads(json.dumps(report.to_dict()))
    assert data["requests"] == report.requests > 0
    assert set(data["routes"]) == set(probe_mod.ROUTES)


def test_stop_event_ends_run_early(server):
    base, ws = server
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    started = time.monotonic()
    Probe(base, ws, APP).run(duration_sec=60, concurrency=2, stop_event=stop)
    assert time.monotonic() - started < 10


def test_fetch_all_rows_pages_through_every_run(server):
    base, ws = server
    rows = fetch_all_rows(base, ws, APP, page_size=7)

    assert len(rows) == sum(EXPECTED.values())
    assert status_counts(rows) == EXPECTED
    names = by_name(rows)
    assert len(names) == len(rows)
    assert names["live-000000"]["status"] == "running"
    assert names["hist-000000"]["status"] == "succeeded"


def test_fetch_all_rows_filters_by_query(server):
    base, ws = server
    rows = fetch_all_rows(base, ws, APP, page_size=7, query='name ~ "live-"')

    assert sorted(by_name(rows)) == sorted(LIVE_NAMES)
    assert status_counts(rows) == {"running": EXPECTED["running"]}
