"""uiload driver: job packing, live view rendering, and a tiny end-to-end
check (real UI server + real worker processes) whose API statuses must agree
with the event oracle."""
import dataclasses
import json

import pytest

pytest.importorskip("fastapi")

from uiload import driver, live_view, scenario

TINY = dataclasses.replace(
    scenario.get_profile("smoke"), name="smoke", seeded_runs=60, seeded_sweeps=1,
    seeded_inner_per_sweep=5, live_jobs=8,
    live_sweeps=1, live_inner_per_sweep=3, duration_sec=18, heartbeat_sec=0.5,
    min_stale_sec=2, probe_concurrency=2,
)


def _job(job_id, behavior, kind="single", children=()):
    return {"job_id": job_id, "behavior": behavior, "kind": kind, "children": list(children)}


def test_pack_jobs_isolates_process_level_and_killed_jobs():
    jobs = [_job("a", "succeed"), _job("b", "stuck"), _job("c", "crash"),
            _job("d", "killed"), _job("e", "recovers", "outer", [_job("e1", "succeed", "inner")]),
            _job("f", "endless")]

    groups = driver.pack_jobs(jobs, per_process=10)

    kinds = sorted((g.kind, tuple(j["job_id"] for j in g.jobs)) for g in groups)
    assert kinds == [("killed", ("d",)), ("worker", ("a", "c", "f")),
                     ("worker", ("b",)), ("worker", ("e",))]


def test_pack_jobs_caps_jobs_per_process():
    jobs = [_job(f"j{i}", "succeed") for i in range(7)]

    groups = driver.pack_jobs(jobs, per_process=3)

    assert [len(g.jobs) for g in groups] == [3, 3, 1]


def test_render_shows_expected_vs_api_and_latency():
    snap = live_view.Snapshot(
        elapsed_sec=12.5, processes=4, spawned_jobs=20,
        expected={"running": 5, "succeeded": 3}, ambiguous=2,
        api_live={"running": 5, "succeeded": 2}, api_hist={"succeeded": 100},
        mismatches=["live-000003: expected succeeded, api running"],
        latency={"list.first": {"count": 10, "p50": 4.0, "p95": 9.5}},
        freshness_sec=0.8,
    )

    text = live_view.render(snap)

    assert "running" in text and "succeeded" in text
    assert "list.first" in text and "9.5" in text
    assert "live-000003" in text
    assert "0.8" in text


@pytest.fixture(scope="module")
def checked(tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("uiload")
    return run_dir, driver.run_check(TINY, str(run_dir), browser=False, rng_seed=7)


def test_check_mode_statuses_agree_with_the_oracle(checked):
    _, report = checked

    assert report["mismatches"] == []
    assert report["compared"] >= 5
    assert sum(report["api_live"].values()) >= TINY.live_jobs


def test_check_mode_reports_latency_and_writes_json(checked):
    run_dir, report = checked

    assert report["probe"]["requests"] > 0
    assert "list.first" in report["probe"]["routes"]
    saved = json.loads((run_dir / "report.json").read_text())
    assert saved["profile"] == "smoke"


def test_check_mode_tears_everything_down(checked):
    _, report = checked

    assert report["leftover_pids"] == []


def test_failures_flattens_every_reason():
    report = {"slo_violations": ["list p95"], "mismatches": ["live-1: x"],
              "browser": {"violations": ["chart"]}, "leftover_pids": [42]}

    assert driver.failures(report) == ["list p95", "live-1: x", "chart", "leftover process 42"]


def test_check_mode_waits_for_the_seeded_history_to_be_indexed(checked):
    _, report = checked

    assert report["seeded"]["index_ready_sec"] >= 0
    assert sum(report["api_hist"].values()) == report["seeded"]["total"]


def test_a_probe_crash_is_a_reported_failure_not_a_harness_crash():
    report = {"slo_violations": [], "mismatches": [], "leftover_pids": [],
              "probe_error": "ReadTimeout('timed out')"}

    assert driver.failures(report) == ["probe crashed: ReadTimeout('timed out')"]
