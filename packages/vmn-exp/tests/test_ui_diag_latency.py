"""The latency section: is the server process itself starved? An asyncio
probe on the server's loop and a daemon-thread probe measure how late their
sleeps wake up, over the last few minutes."""
import asyncio
import time

import pytest

from vmn_exp.ui import diag
from vmn_exp.ui.diag import latency, registry


@pytest.fixture(autouse=True)
def _isolated_sections(monkeypatch):
    monkeypatch.setattr(registry, "_SECTIONS", dict(registry._SECTIONS))


def test_lag_stats_summarize_and_remember_the_worst():
    stats = latency.LagStats(window_sec=300)
    for lag in (0.001, 0.002, 0.003, 0.5, 0.004):
        stats.add(lag)
    summary = stats.summary()
    assert summary["samples"] == 5
    assert summary["max_ms"] == pytest.approx(500, abs=0.01)
    assert summary["last_ms"] == pytest.approx(4, abs=0.01)
    assert summary["p50_ms"] == pytest.approx(3, abs=0.01)
    assert summary["p95_ms"] == pytest.approx(500, abs=0.01)
    assert isinstance(summary["worst_at"], float)


def test_lag_stats_with_no_samples():
    summary = latency.LagStats().summary()
    assert summary["samples"] == 0 and summary["max_ms"] is None and summary["worst_at"] is None


def test_lag_stats_drop_samples_older_than_the_window(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(latency.time, "monotonic", lambda: now[0])
    stats = latency.LagStats(window_sec=10)
    stats.add(0.9)
    now[0] += 11
    stats.add(0.001)
    summary = stats.summary()
    assert summary["samples"] == 1 and summary["max_ms"] == pytest.approx(1, abs=0.01)


def test_the_lag_stats_are_bounded():
    stats = latency.LagStats(window_sec=1, interval_sec=0.1)
    for _ in range(1000):
        stats.add(0.0)
    assert stats.summary()["samples"] < 100


def test_a_thread_probe_measures_its_sleep_overshoot():
    stats = latency.LagStats()
    latency.thread_probe_step(stats, 0.01, sleep=lambda s: time.sleep(s + 0.05))
    assert stats.summary()["last_ms"] >= 45


def test_the_thread_probe_starts_once_per_process():
    first = latency.start_thread_probe()
    assert first.daemon and first.is_alive()
    assert latency.start_thread_probe() is first


def test_a_loop_probe_sees_a_blocked_event_loop():
    stats = latency.LagStats()

    async def scenario():
        task = asyncio.ensure_future(latency.loop_probe(stats, 0.02))
        await asyncio.sleep(0.05)
        time.sleep(0.3)  # the loop is blocked
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(scenario())
    assert stats.summary()["max_ms"] >= 250


def test_the_server_runs_the_loop_probe_and_reports_both_probes(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app = create_app(WorkspaceManager(str(tmp_path / "data")))
    with TestClient(app) as client:
        assert client.get("/api/v1/workspaces").status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            section = diag.build_dump()["sections"]["latency"]
            if section["event_loop"]["samples"]:
                break
            time.sleep(0.05)
    assert section["event_loop"]["samples"] >= 1
    assert section["event_loop"]["interval_sec"] == latency.LOOP_INTERVAL_SEC
    assert section["thread"]["interval_sec"] == latency.THREAD_INTERVAL_SEC
    assert {"p50_ms", "p95_ms", "max_ms", "last_ms", "samples", "worst_at"} <= set(
        section["thread"])
