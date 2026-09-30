"""Unit tests for the uiload scenario planner (pure Python, no Docker)."""
import dataclasses
import json

import pytest
from uiload import scenario

PROCESS_LEVEL = {"oom", "stuck", "recovers"}
INNER_OK = {"succeed", "crash", "chatty", "wide", "endless"}
JOB_KEYS = {
    "job_id", "behavior", "kind", "parent_job", "params", "tags",
    "metric_keys", "steps", "step_sleep_sec", "fail_at_step",
    "stop_at_step", "resume_after_sec", "kill_after_sec", "children",
}


def _all(jobs):
    return list(scenario.flatten(jobs))


def test_profiles_match_contract():
    smoke = scenario.get_profile("smoke")
    assert (smoke.seeded_runs, smoke.live_jobs) == (500, 30)
    assert (smoke.live_sweeps, smoke.live_inner_per_sweep) == (2, 5)
    assert (smoke.duration_sec, smoke.heartbeat_sec, smoke.min_stale_sec) == (45, 1, 5)
    load = scenario.PROFILES["load"]
    assert (load.seeded_runs, load.seeded_sweeps, load.seeded_inner_per_sweep) == (
        100_000, 200, 50)
    assert (load.live_jobs, load.live_sweeps, load.live_inner_per_sweep) == (500, 20, 20)
    assert (load.duration_sec, load.heartbeat_sec, load.min_stale_sec) == (300, 2, 8)
    soak = scenario.PROFILES["soak"]
    assert (soak.seeded_runs, soak.live_jobs, soak.duration_sec) == (250_000, 2000, 0)
    assert (soak.heartbeat_sec, soak.min_stale_sec) == (2, 10)
    assert set(smoke.behavior_weights) == set(scenario.BEHAVIORS)


def test_profile_is_frozen_and_stale_sec():
    smoke = scenario.get_profile("smoke")
    with pytest.raises(dataclasses.FrozenInstanceError):
        smoke.live_jobs = 1
    assert smoke.stale_sec == 5
    assert scenario.PROFILES["load"].stale_sec == 8


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        scenario.get_profile("nope")


def test_plan_is_deterministic_and_json_serialisable():
    smoke = scenario.get_profile("smoke")
    a = scenario.plan_live(smoke, 7)
    assert a == scenario.plan_live(smoke, 7)
    assert a != scenario.plan_live(smoke, 8)
    json.dumps(a)


def test_plan_counts_and_sweeps():
    smoke = scenario.get_profile("smoke")
    jobs = scenario.plan_live(smoke, 1)
    assert len(jobs) == smoke.live_jobs
    outers = [j for j in jobs if j["kind"] == "outer"]
    assert len(outers) == smoke.live_sweeps
    for outer in outers:
        assert len(outer["children"]) == smoke.live_inner_per_sweep
        for child in outer["children"]:
            assert child["kind"] == "inner"
            assert child["parent_job"] == outer["job_id"]
            assert child["children"] == []
    assert all(j["parent_job"] is None for j in jobs)


def test_job_ids_unique_sequential_and_continue_from_start_index():
    smoke = scenario.get_profile("smoke")
    jobs = _all(scenario.plan_live(smoke, 1))
    ids = [j["job_id"] for j in jobs]
    assert sorted(ids) == [f"live-{i:06d}" for i in range(len(ids))]
    more = scenario.plan_live(smoke, 1, start_index=len(ids), count=5)
    assert len(more) == 5
    assert more[0]["job_id"] == f"live-{len(ids):06d}"


def test_job_dict_shape_and_rules():
    profile = scenario.get_profile("load")
    for job in _all(scenario.plan_live(profile, 3)):
        assert set(job) == JOB_KEYS
        assert job["metric_keys"] and "probe_ts" not in job["metric_keys"]
        assert job["steps"] <= profile.max_steps
        if job["kind"] == "inner":
            assert job["behavior"] in INNER_OK
        if job["behavior"] == "killed":
            assert job["kind"] == "single"
        assert job["tags"]["behavior"] == job["behavior"]


def test_behavior_fields_are_consistent():
    profile = scenario.get_profile("load")
    seen = set()
    for job in _all(scenario.plan_live(profile, 5)):
        b = job["behavior"]
        seen.add(b)
        assert (job["fail_at_step"] is not None) == (b in {"crash", "oom"})
        assert (job["stop_at_step"] is not None) == (b in {"stuck", "recovers"})
        assert (job["resume_after_sec"] is not None) == (b == "recovers")
        assert (job["kill_after_sec"] is not None) == (b == "killed")
        for key in ("fail_at_step", "stop_at_step"):
            if job[key] is not None:
                assert 0 < job[key] < job["steps"]
        if b == "recovers":
            assert job["resume_after_sec"] > profile.stale_sec
    assert seen == set(scenario.BEHAVIORS)


def test_process_level_behaviors_only_on_single_or_outer():
    profile = scenario.get_profile("load")
    for job in _all(scenario.plan_live(profile, 11)):
        if job["behavior"] in PROCESS_LEVEL:
            assert job["kind"] in {"single", "outer"}


def test_endless_inner_only_under_endless_outer():
    profile = scenario.get_profile("load")
    for job in scenario.plan_live(profile, 12):
        for child in job["children"]:
            if child["behavior"] == "endless":
                assert job["behavior"] == "endless"


def test_params_are_realistic_and_bounded():
    smoke = scenario.get_profile("smoke")
    for job in _all(scenario.plan_live(smoke, 2)):
        params = job["params"]
        assert isinstance(params["lr"], float)
        assert isinstance(params["batch_size"], int)
        assert isinstance(params["optimizer"], str)
        assert isinstance(params["use_amp"], bool)
        if job["behavior"] == "wide":
            assert len(params) >= 50
            assert 300 <= len(job["metric_keys"]) <= 1000
        else:
            assert len(params) <= smoke.max_params
            assert len(job["metric_keys"]) <= smoke.max_metric_keys


def test_smoke_jobs_live_a_few_seconds():
    smoke = scenario.get_profile("smoke")
    for job in _all(scenario.plan_live(smoke, 4)):
        life = job["steps"] * job["step_sleep_sec"]
        assert 5 <= life <= 30, job
        if job["behavior"] == "chatty":
            assert job["step_sleep_sec"] <= 0.02


def test_flatten_yields_nested_children():
    outer = {"job_id": "o", "children": [{"job_id": "i", "children": []}]}
    single = {"job_id": "s", "children": []}
    assert [j["job_id"] for j in scenario.flatten([outer, single])] == ["o", "i", "s"]
