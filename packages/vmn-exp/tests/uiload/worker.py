#!/usr/bin/env python3
"""A live uiload job process: runs a list of job dicts concurrently via the SDK.

    python packages/vmn-exp/tests/uiload/worker.py --root R --app A --run-dir D --jobs-file F [--heartbeat-sec S]

Git-free: runs record against a stub exported snapshot (``VMN_SNAPSHOT_METADATA``)
into ``VMN_EXPERIMENT_DIR=<root>/.vmn/store``, i.e. ``.vmn/store/runs/<app>/`` — the
directory ``vmn-exp ui --repo <root>`` serves. The worker sets that env itself
from ``--root``; :func:`prepare_snapshot_env` builds the same env for launchers.

Job behaviors and events follow the uiload contract. Two extras:

* ``endless`` jobs log until the process is sent SIGTERM (teardown); the SDK
  finalizes every open run as exit 143 and the worker then exits 143. SIGKILL
  leaves them to go stale (``stuck``) like any dead writer.
* ``killed`` jobs are not run here: :func:`killed_command` builds the
  ``vmn-exp run`` invocation (child: ``packages/vmn-exp/tests/uiload/child.py``) the driver spawns.
"""
import argparse
import json
import math
import os
import random
import signal
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
CHILD = os.path.join(HERE, "child.py")
SRC_DIRS = [os.path.join(REPO, "packages", d, "src") for d in ("vmn", "vmn-exp-sdk", "vmn-exp")]
CODE_VERSTR = "0.0.1-dev.10ad7e5.0ad0ad0"
OWNED_ENV = ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID", "VMN_WORKING_DIR")
STOP_BEHAVIORS = ("stuck", "recovers")
FINAL_UPLOAD_TIMEOUT_SEC = "10"


# -- environment -------------------------------------------------------------


def write_snapshot_metadata(app, run_dir):
    """The minimal ``vmn-exp export`` metadata runs are recorded against."""
    path = os.path.join(run_dir, "vmn_metadata.yml")
    if not os.path.exists(path):
        os.makedirs(run_dir, exist_ok=True)
        with open(path + f".{os.getpid()}", "w") as f:
            f.write(f"verstr: {CODE_VERSTR}\napp_name: {app}\nbase_version: 0.0.1\n"
                    f"base_commit: {'10ad7e5' * 5}10ad7\nbranch: main\n")
        os.replace(path + f".{os.getpid()}", path)
    return path


def snapshot_env_vars(root, app, run_dir):
    return {
        "VMN_SNAPSHOT_METADATA": write_snapshot_metadata(app, run_dir),
        "VMN_EXPERIMENT_DIR": os.path.join(os.path.abspath(root), ".vmn", "store"),
        "VMN_CAPTURE_ENV": "0",
        # Teardown SIGTERMs job processes; don't let a hung store hold one for
        # the SDK's default minute of final-upload waiting.
        "VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC": FINAL_UPLOAD_TIMEOUT_SEC,
    }


def with_src_pythonpath(env):
    """Put the checkout's package sources first on *env*'s ``PYTHONPATH``, so
    child processes run the tree under test."""
    env["PYTHONPATH"] = os.pathsep.join(SRC_DIRS + [p for p in [env.get("PYTHONPATH")] if p])
    return env


def prepare_snapshot_env(root, app, run_dir):
    """The full environment to launch workers (and ``vmn-exp run``) with."""
    env = {k: v for k, v in os.environ.items() if k not in OWNED_ENV}
    env.update(snapshot_env_vars(root, app, run_dir))
    with_src_pythonpath(env)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def worker_command(root, app, run_dir, jobs_file, heartbeat_sec=None):
    cmd = [sys.executable, os.path.abspath(__file__), "--root", root, "--app", app,
           "--run-dir", run_dir, "--jobs-file", jobs_file]
    return cmd + (["--heartbeat-sec", str(heartbeat_sec)] if heartbeat_sec else [])


def killed_command(job, root, app, run_dir, env, heartbeat_sec=1):
    """``vmn-exp run --name <job_id> ... -- python child.py ...`` for a killed job.

    *env* must be :func:`prepare_snapshot_env`'s (it carries the snapshot mode).
    ``--heartbeat-interval`` only takes whole seconds.
    """
    assert env.get("VMN_SNAPSHOT_METADATA"), "use prepare_snapshot_env()"
    return [
        sys.executable, "-m", "vmn_exp.cli", "run", app, "--name", job["job_id"],
        "--experiment-dir", os.path.join(root, ".vmn", "store"), "--no-env",
        "--heartbeat-interval", str(max(1, round(heartbeat_sec))),
        "--", sys.executable, CHILD, "--job-id", job["job_id"], "--run-dir", run_dir,
        "--steps", str(job.get("steps") or 100000),
        "--step-sleep-sec", str(job.get("step_sleep_sec") or 0.05),
        "--metric-keys", ",".join(job.get("metric_keys") or ["loss", "acc"]),
    ]


def is_stopped(pid):
    """Whether *pid* is stopped. A "stopping" job emits its event *before* it
    SIGSTOPs itself, and a SIGCONT that lands first is lost for good."""
    import psutil

    try:
        return psutil.Process(pid).status() == psutil.STATUS_STOPPED
    except psutil.Error:
        return False


# -- events and metrics --------------------------------------------------------


class EventLog:
    """Thread-safe appends to ``<run_dir>/events/<name>.jsonl`` (default ``worker-<pid>``)."""

    def __init__(self, run_dir, name=None):
        events_dir = os.path.join(run_dir, "events")
        os.makedirs(events_dir, exist_ok=True)
        name = name or f"worker-{os.getpid()}"
        self._file = open(os.path.join(events_dir, f"{name}.jsonl"), "a")
        self._lock = threading.Lock()

    def emit(self, job_id, event, sync=False, **extra):
        line = {"t": time.time(), "job_id": job_id, "event": event, "pid": os.getpid()}
        line.update(extra)
        with self._lock:
            self._file.write(json.dumps(line) + "\n")
            self._file.flush()
            if sync:
                os.fsync(self._file.fileno())


def metric_values(keys, step, steps, rng):
    """Plausible curves: ``acc``-like keys rise, everything else decays; plus noise."""
    t = step / max(1, steps - 1)
    values = {}
    for i, key in enumerate(keys):
        decay = math.exp(-(2 + i % 5) * t)
        base = 1 - 0.9 * decay if "acc" in key else decay + (i % 7) * 0.1
        values[key] = round(base + rng.gauss(0, 0.02), 6)
    values["probe_ts"] = time.time()
    return values


# -- jobs ----------------------------------------------------------------------


class Worker:
    """Runs jobs on threads, one SDK run per job."""

    def __init__(self, app, events, heartbeat_sec):
        self.app, self.events, self.heartbeat_sec = app, events, heartbeat_sec
        self.open_jobs = {}

    def start(self, job, parent):
        from vmn_exp.sdk import start_run

        return start_run(
            self.app, name=job["job_id"], params=job.get("params") or None,
            tags=job.get("tags") or None, parent=parent,
            capture_env=False, heartbeat_interval_sec=self.heartbeat_sec,
        )

    def run_job(self, job, parent=None):
        try:
            run = self.start(job, parent)
        except Exception:
            traceback.print_exc()
            return
        self.events.emit(job["job_id"], "started", verstr=run.id)
        exit_code = 0
        try:
            with run:
                self.open_jobs[job["job_id"]] = run
                try:
                    self._body(job, run)
                finally:
                    self.open_jobs.pop(job["job_id"], None)
        except Exception:
            exit_code = 1
        self.events.emit(job["job_id"], "finished", sync=True, exit_code=exit_code)

    def _body(self, job, run):
        children = [threading.Thread(target=self.run_job, args=(c, run.id), daemon=True)
                    for c in job.get("children") or []]
        for thread in children:
            thread.start()
        try:
            self._steps(job, run)
        finally:
            for thread in children:
                thread.join()

    def _steps(self, job, run):
        behavior, steps = job["behavior"], int(job.get("steps") or 1)
        keys = job.get("metric_keys") or ["loss", "acc"]
        rng = random.Random(job["job_id"])
        step = 0
        while behavior == "endless" or step < steps:
            self._maybe_fail(job, step)
            values = metric_values(keys, step, steps, rng)
            if behavior == "chatty":
                for key, value in values.items():
                    run.log_metric(key, value, step=step)
            else:
                run.log_metrics(values, step=step)
            time.sleep(float(job.get("step_sleep_sec") or 0))
            step += 1

    def _maybe_fail(self, job, step):
        behavior, job_id = job["behavior"], job["job_id"]
        if step == job.get("stop_at_step") and behavior in STOP_BEHAVIORS:
            self.events.emit(job_id, "stopping", sync=True,
                             resume_after_sec=job.get("resume_after_sec"))
            os.kill(os.getpid(), signal.SIGSTOP)
        if step == job.get("fail_at_step"):
            if behavior == "oom":
                self.events.emit(job_id, "oom", sync=True)
                os._exit(137)
            if behavior == "crash":
                raise RuntimeError(f"{job_id}: simulated crash at step {step}")

    def terminate(self, signum, _frame):
        """SIGTERM, chained after the SDK finalized the open runs: record their
        jobs as finished with 128+N and exit with it."""
        code = 128 + signum
        for job_id in list(self.open_jobs):
            self.events.emit(job_id, "finished", sync=True, exit_code=code)
        os._exit(code)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="uiload live worker")
    parser.add_argument("--root", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--jobs-file", required=True)
    parser.add_argument("--heartbeat-sec", type=float, default=2.0)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    for key in OWNED_ENV:
        os.environ.pop(key, None)
    os.environ.update(snapshot_env_vars(args.root, args.app, args.run_dir))
    with open(args.jobs_file) as f:
        jobs = json.load(f)
    worker = Worker(args.app, EventLog(args.run_dir), args.heartbeat_sec)
    signal.signal(signal.SIGTERM, worker.terminate)
    from vmn_exp.sdk import install_signal_handlers

    install_signal_handlers()  # after ours, so it chains to worker.terminate
    threads = [threading.Thread(target=worker.run_job, args=(job,), daemon=True)
               for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        while thread.is_alive():
            thread.join(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
