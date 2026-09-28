"""The uiload live worker: real processes, real SDK runs, derived statuses.

One module fixture launches every scenario at once (so the module stays fast)
and each test waits for the outcome it cares about.
"""
import json
import os
import signal
import subprocess
import sys
import time

import pytest
from uiload import worker
from vmn_exp.sdk.reader import list_runs
from vmn_exp.storage.cached import get_snapshot_storage

APP = "loadapp"
HB = 0.5
STALE = 2


def _job(job_id, behavior, kind="single", steps=6, **extra):
    job = {
        "job_id": job_id, "behavior": behavior, "kind": kind, "parent_job": None,
        "params": {"lr": 0.01, "opt": "adam"}, "tags": {"team": "load"},
        "metric_keys": ["loss", "acc"], "steps": steps, "step_sleep_sec": 0.05,
        "fail_at_step": None, "stop_at_step": None, "resume_after_sec": None,
        "kill_after_sec": None, "children": [],
    }
    job.update(extra)
    return job


def _outer():
    kids = [
        _job(f"live-00001{i}", "succeed", kind="inner", parent_job="live-000010")
        for i in (1, 2)
    ]
    return _job("live-000010", "succeed", kind="outer", children=kids)


def _spawn_worker(root, run_dir, env, name, jobs):
    jobs_file = os.path.join(run_dir, f"{name}.json")
    with open(jobs_file, "w") as f:
        json.dump(jobs, f)
    cmd = worker.worker_command(root, APP, run_dir, jobs_file, heartbeat_sec=HB)
    return subprocess.Popen(cmd, env=env)


@pytest.fixture(scope="module")
def launched(tmp_path_factory):
    base = tmp_path_factory.mktemp("uiload_worker")
    root, run_dir = str(base / "root"), str(base / "run")
    os.makedirs(os.path.join(root, ".git"))
    os.makedirs(run_dir)
    env = worker.prepare_snapshot_env(root, APP, run_dir)
    procs = {
        "main": _spawn_worker(root, run_dir, env, "main", [
            _job("live-000001", "succeed"),
            _job("live-000002", "crash", fail_at_step=2),
            _job("live-000003", "chatty"),
            _outer(),
        ]),
        "oom": _spawn_worker(root, run_dir, env, "oom",
                             [_job("live-000004", "oom", steps=50, fail_at_step=2)]),
        "stuck": _spawn_worker(root, run_dir, env, "stuck",
                               [_job("live-000005", "stuck", steps=50, stop_at_step=2)]),
        "recovers": _spawn_worker(root, run_dir, env, "recovers", [
            _job("live-000006", "recovers", stop_at_step=2, resume_after_sec=0.5)]),
    }
    procs["endless"] = _spawn_worker(root, run_dir, env, "endless",
                                     [_job("live-000008", "endless")])
    procs["crowd"] = _spawn_worker(root, run_dir, env, "crowd", [
        _job(f"live-0001{i:02d}", "succeed", steps=3) for i in range(20)])
    killed = _job("live-000007", "killed", steps=1000, kill_after_sec=1)
    procs["killed"] = subprocess.Popen(
        worker.killed_command(killed, root, APP, run_dir, env, heartbeat_sec=1), env=env
    )
    yield {"root": root, "run_dir": run_dir, "procs": procs}
    for proc in procs.values():
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _storage(root):
    return get_snapshot_storage("local", vmn_root_path=root, subdir="experiments")


def _rows(root):
    return {r.get("name"): r for r in list_runs(APP, storage=_storage(root), use_index=False)}


def _wait_for(predicate, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("timed out waiting")


def _status_is(root, name, status):
    return lambda: _rows(root).get(name, {}).get("status") == status


def _events(run_dir):
    events = []
    events_dir = os.path.join(run_dir, "events")
    for fname in sorted(os.listdir(events_dir)) if os.path.isdir(events_dir) else []:
        with open(os.path.join(events_dir, fname)) as f:
            events += [json.loads(line) for line in f if line.strip()]
    return events


def _events_of(run_dir, job_id):
    return [e["event"] for e in _events(run_dir) if e["job_id"] == job_id]


@pytest.fixture(autouse=True)
def fast_stale(monkeypatch):
    monkeypatch.setenv("VMN_EXP_MIN_STALE_SEC", str(STALE))


def test_records_land_where_the_ui_reads(launched):
    root = launched["root"]
    _wait_for(_status_is(root, "live-000001", "succeeded"))
    exp_dir = os.path.join(root, ".vmn", APP, "experiments")
    row = _rows(root)["live-000001"]
    assert os.path.isdir(os.path.join(exp_dir, row["verstr"]))


def test_succeed_and_chatty_succeed(launched):
    root = launched["root"]
    for name in ("live-000001", "live-000003"):
        _wait_for(_status_is(root, name, "succeeded"))
    metrics = _rows(root)["live-000001"]["metrics"]
    assert {"loss", "acc", "probe_ts"} <= set(metrics)


def test_crash_fails_with_exit_1(launched):
    root = launched["root"]
    _wait_for(_status_is(root, "live-000002", "failed"))
    assert _rows(root)["live-000002"]["exit_code"] == 1


def test_outer_hosts_inner_runs(launched):
    root = launched["root"]
    _wait_for(_status_is(root, "live-000010", "succeeded"))
    rows = _rows(root)
    outer = rows["live-000010"]
    assert outer["kind"] == "outer"
    for name in ("live-000011", "live-000012"):
        assert rows[name]["kind"] == "inner"
        assert rows[name]["parent"] == outer["verstr"]
        assert rows[name]["status"] == "succeeded"
    assert rows["live-000001"].get("parent") is None
    assert launched["procs"]["main"].wait(timeout=20) == 0


def test_oom_goes_stuck(launched):
    root = launched["root"]
    assert launched["procs"]["oom"].wait(timeout=20) == 137
    _wait_for(_status_is(root, "live-000004", "stuck"))
    assert _events_of(launched["run_dir"], "live-000004") == ["started", "oom"]


def test_stuck_goes_stuck(launched):
    root = launched["root"]
    _wait_for(lambda: "stopping" in _events_of(launched["run_dir"], "live-000005"))
    _wait_for(_status_is(root, "live-000005", "stuck"))


def test_recovers_after_sigcont(launched):
    root, run_dir = launched["root"], launched["run_dir"]
    _wait_for(lambda: "stopping" in _events_of(run_dir, "live-000006"))
    stopping = [e for e in _events(run_dir) if e["event"] == "stopping"
                and e["job_id"] == "live-000006"][0]
    assert stopping["resume_after_sec"] == 0.5
    time.sleep(0.5)
    os.kill(stopping["pid"], signal.SIGCONT)
    _wait_for(_status_is(root, "live-000006", "succeeded"))
    assert _events_of(run_dir, "live-000006") == ["started", "stopping", "finished"]


def test_killed_via_vmn_exp_run_fails_143(launched):
    root, proc = launched["root"], launched["procs"]["killed"]
    _wait_for(_status_is(root, "live-000007", "running"))
    _wait_for(lambda: "probe_ts" in _rows(root)["live-000007"].get("metrics", {}))
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=20)
    _wait_for(_status_is(root, "live-000007", "failed"))
    assert _rows(root)["live-000007"]["exit_code"] == 143


def test_endless_runs_until_sigterm(launched):
    root, proc = launched["root"], launched["procs"]["endless"]
    _wait_for(_status_is(root, "live-000008", "running"))
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=20) == 143
    row = _rows(root)["live-000008"]
    assert row["status"] == "failed" and row["exit_code"] == 143
    assert _events_of(launched["run_dir"], "live-000008") == ["started", "finished"]


def test_concurrent_singles_are_never_parented(launched):
    assert launched["procs"]["crowd"].wait(timeout=30) == 0
    rows = _rows(launched["root"])
    crowd = [rows[f"live-0001{i:02d}"] for i in range(20)]
    assert all(r["status"] == "succeeded" and r.get("parent") is None for r in crowd)


def test_events_describe_each_job(launched):
    run_dir = launched["run_dir"]
    _wait_for(lambda: launched["procs"]["main"].poll() is not None)
    events = _events(run_dir)
    finished = {e["job_id"]: e["exit_code"] for e in events if e["event"] == "finished"}
    assert finished["live-000001"] == 0 and finished["live-000002"] == 1
    assert finished["live-000011"] == 0 and finished["live-000010"] == 0
    started = [e for e in events if e["event"] == "started" and e["job_id"] == "live-000001"]
    assert started[0]["verstr"] and started[0]["pid"] and started[0]["t"]
    assert os.path.basename(
        os.path.join(run_dir, "events", f"worker-{launched['procs']['main'].pid}.jsonl")
    ) in os.listdir(os.path.join(run_dir, "events"))


def test_worker_module_runs_as_script():
    out = subprocess.run(
        [sys.executable, worker.__file__, "--help"], capture_output=True, text=True
    )
    assert out.returncode == 0 and "--jobs-file" in out.stdout


def test_job_processes_give_up_on_final_uploads_within_teardown(tmp_path):
    # Teardown SIGTERMs every job process; a hung store must not hold one for
    # the SDK's default minute of final-upload waiting.
    env = worker.snapshot_env_vars(str(tmp_path), APP, str(tmp_path / "run"))
    assert env["VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC"] == "10"
