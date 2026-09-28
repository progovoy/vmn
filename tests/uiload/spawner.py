"""Keeps a profile's live population running: spawns worker processes, resumes
``recovers`` jobs, SIGTERMs ``killed`` jobs, reaps the dead, and writes the
driver's events (``events/driver.jsonl``) the oracle needs."""
import dataclasses
import json
import os
import signal
import subprocess
import time

from uiload import scenario
from uiload.worker import EventLog, killed_command, prepare_snapshot_env, worker_command

SPAWN_BATCH = 50  # top-level jobs per tick: creation is serialized by the repo lock
FROZEN_REAP_FACTOR = 3  # SIGKILL a never-resumed stuck process after 3 stale windows


@dataclasses.dataclass
class Group:
    jobs: list
    proc: subprocess.Popen = None
    spawned_t: float = 0.0
    stopped_t: float = None
    signalled: bool = False
    resumed: bool = False

    @property
    def kind(self):
        """``killed`` jobs run under ``vmn-exp run``; everything else in a worker."""
        return "killed" if self.behavior == "killed" else "worker"

    @property
    def behavior(self):
        return self.jobs[0]["behavior"]

    @property
    def job_id(self):
        return self.jobs[0]["job_id"]


def pack_jobs(jobs, per_process):
    """One process per ``killed`` job and per process-level (stop/oom) job;
    every other top-level job shares a worker process, *per_process* at most."""
    alone = scenario.PROCESS_LEVEL | {"killed"}
    groups = [Group([job]) for job in jobs if job["behavior"] in alone]
    shared = [job for job in jobs if job["behavior"] not in alone]
    groups += [Group(shared[i:i + per_process]) for i in range(0, len(shared), per_process)]
    return groups


def _exit_code(returncode):
    return 128 - returncode if returncode < 0 else returncode


class Spawner:
    def __init__(self, profile, root, app, run_dir, rng_seed=0, per_process=20):
        self.profile, self.root, self.app, self.run_dir = profile, root, app, run_dir
        self.rng_seed, self.per_process = rng_seed, per_process
        self.env = prepare_snapshot_env(root, app, run_dir)
        self.events = EventLog(run_dir, name="driver")
        self.groups, self.next_index = [], 0
        os.makedirs(os.path.join(run_dir, "jobs"), exist_ok=True)
        self.log = open(os.path.join(run_dir, "workers.log"), "ab")

    @property
    def spawned_jobs(self):
        """Every planned job (inner ones included) is spawned in the same tick."""
        return self.next_index

    # -- population ------------------------------------------------------------

    def active_jobs(self):
        return sum(len(g.jobs) for g in self.groups if g.stopped_t is None or g.behavior == "recovers")

    def tick(self, accept_new=True):
        now = time.time()
        self._reap()
        for group in self.groups:
            self._drive(group, now)
        if accept_new:
            self._replenish()

    def _replenish(self):
        need = min(self.profile.live_jobs - self.active_jobs(), SPAWN_BATCH)
        if need <= 0:
            return
        jobs = scenario.plan_live(self.profile, self.rng_seed, start_index=self.next_index, count=need)
        self.next_index += len(list(scenario.flatten(jobs)))
        for group in pack_jobs(jobs, self.per_process):
            self._spawn(group)

    def _spawn(self, group):
        if group.kind == "killed":
            cmd = killed_command(group.jobs[0], self.root, self.app, self.run_dir, self.env,
                                 heartbeat_sec=self.profile.heartbeat_sec)
        else:
            jobs_file = os.path.join(self.run_dir, "jobs", f"{group.job_id}.json")
            with open(jobs_file, "w") as f:
                json.dump(group.jobs, f)
            cmd = worker_command(self.root, self.app, self.run_dir, jobs_file,
                                 heartbeat_sec=self.profile.heartbeat_sec)
        group.proc = subprocess.Popen(cmd, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        group.spawned_t = time.time()
        self.groups.append(group)
        for job in group.jobs:
            self.events.emit(job["job_id"], "spawned", pid=group.proc.pid)

    # -- per-process fate --------------------------------------------------------

    def _drive(self, group, now):
        job = group.jobs[0]
        if group.kind == "killed" and not group.signalled and now >= group.spawned_t + job["kill_after_sec"]:
            group.signalled = True
            self.events.emit(group.job_id, "signalled", pid=group.proc.pid, signal="SIGTERM")
            group.proc.send_signal(signal.SIGTERM)
        if group.behavior in ("stuck", "recovers") and group.stopped_t is None and not group.resumed:
            group.stopped_t = self._stopped_at(group)
        if group.stopped_t is None:
            return
        if group.behavior == "recovers" and now >= group.stopped_t + job["resume_after_sec"]:
            self.events.emit(group.job_id, "resumed", pid=group.proc.pid)
            group.proc.send_signal(signal.SIGCONT)
            group.stopped_t, group.resumed = None, True
        elif group.behavior == "stuck" and now >= group.stopped_t + FROZEN_REAP_FACTOR * self.profile.stale_sec:
            group.proc.kill()  # stays stuck in the UI; frees the memory

    def _stopped_at(self, group):
        path = os.path.join(self.run_dir, "events", f"worker-{group.proc.pid}.jsonl")
        try:
            with open(path) as f:
                for line in f:
                    if '"stopping"' in line:
                        return json.loads(line)["t"]
        except (OSError, ValueError):
            pass
        return None

    def _reap(self):
        for group in list(self.groups):
            if group.proc.poll() is None:
                continue
            self.groups.remove(group)
            if group.kind == "killed":  # the supervised child may not have written it
                self.events.emit(group.job_id, "finished", pid=group.proc.pid,
                                 exit_code=_exit_code(group.proc.returncode))

    # -- teardown ----------------------------------------------------------------

    def teardown(self, timeout_sec=20):
        for group in self.groups:
            if group.proc.poll() is None:
                self.events.emit(group.job_id, "teardown", pid=group.proc.pid)
                group.proc.send_signal(signal.SIGCONT)
                group.proc.terminate()
        deadline = time.monotonic() + timeout_sec
        for group in self.groups:
            try:
                group.proc.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                group.proc.kill()
                group.proc.wait()
        self.groups = []
        self.log.close()

    def pids(self):
        return [g.proc.pid for g in self.groups]
