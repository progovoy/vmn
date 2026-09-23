#!/usr/bin/env python3
"""Mutation job runner for vmn ui.

Mutations run as ``vmn`` CLI subprocesses so they acquire the per-repo FileLock
naturally (correct serialization against terminal use) and their output is
captured per job without touching vmn's process-global logger. At most one
mutation runs per workspace at a time; a crashing job can't take the server
down.
"""
import shutil
import subprocess
import sys
import threading
import uuid
from collections import OrderedDict

# Substrings a successful job's log can carry to mean "ran fine, but there
# was nothing to do" - distinct from actually producing the thing the action
# promised (e.g. `vmn snapshot create` on a clean tree exits 0 and does not
# create a snapshot).
_NOOP_LOG_MARKERS = ("No local changes to snapshot (working tree is clean)",)

# A job that waits on a credential prompt or a lock must not pin its workspace
# forever: it fails after this long and frees the slot.
DEFAULT_JOB_TIMEOUT_SEC = 30 * 60
# The job table lives in memory for the server's lifetime; keep it bounded.
MAX_JOBS = 200
MAX_JOB_LOG_BYTES = 1_000_000
_TRUNCATED_MARKER = "[... earlier output truncated ...]\n"


def _tail(text):
    """The last MAX_JOB_LOG_BYTES of *text* - the end is where errors are."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= MAX_JOB_LOG_BYTES:
        return text
    return _TRUNCATED_MARKER + raw[-MAX_JOB_LOG_BYTES:].decode(
        "utf-8", errors="ignore"
    )


def _as_text(output):
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _metric_args(metrics):
    """Validate a {name: value} mapping and render it as ``--metrics k=v ...``.

    Returns (args, error_message_or_None); ``([], None)`` when there are none.
    """
    metrics = metrics or {}
    for key in metrics:
        if not key or "=" in key or any(c.isspace() for c in key):
            return None, f"Invalid metric name '{key}'"
    if not metrics:
        return [], None
    return ["--metrics"] + [f"{k}={v}" for k, v in metrics.items()], None


def build_command(action, app_name, body):
    """Translate an action + request body into a ``vmn`` argv list.

    Returns (argv, error_message_or_None). Kept pure for testing/preview.
    """
    body = body or {}
    if action == "stamp":
        mode = body.get("release_mode")
        if mode not in ("major", "minor", "patch", "hotfix"):
            return None, "release_mode must be major|minor|patch|hotfix"
        cmd = ["vmn", "stamp", "-r", mode]
        if body.get("prerelease"):
            cmd += ["--pr", body["prerelease"]]
        if body.get("dry_run"):
            cmd += ["--dry-run"]
        cmd.append(app_name)
        return cmd, None

    if action == "release":
        cmd = ["vmn", "release"]
        if body.get("verstr"):
            cmd += ["-v", body["verstr"]]
        cmd.append(app_name)
        return cmd, None

    if action == "restore":
        verstr = body.get("verstr")
        if not verstr:
            return None, "verstr is required"
        return ["vmn", "experiment", "restore", app_name, "-v", verstr], None

    if action == "goto":
        verstr = body.get("verstr")
        cmd = ["vmn", "goto"]
        if verstr:
            cmd += ["-v", verstr]
        cmd.append(app_name)
        return cmd, None

    if action == "prune":
        cmd = ["vmn", "experiment", "prune", app_name]
        if body.get("keep") is not None:
            cmd += ["--keep", str(body["keep"])]
        elif body.get("older_than"):
            cmd += ["--older-than", body["older_than"]]
        else:
            return None, "prune needs keep or older_than"
        return cmd, None

    if action == "exp_create":
        cmd = ["vmn", "experiment", "create", app_name]
        if body.get("note"):
            cmd += ["--note", body["note"]]
        metric_args, err = _metric_args(body.get("metrics"))
        if err:
            return None, err
        return cmd + metric_args, None

    if action == "exp_add":
        verstr = body.get("verstr")
        if not verstr:
            return None, "verstr is required"
        metric_args, err = _metric_args(body.get("metrics"))
        if err:
            return None, err
        note = body.get("note")
        if not metric_args and not note:
            return None, "exp_add needs metrics or a note"
        cmd = ["vmn", "experiment", "add", app_name, "-v", verstr]
        if note:
            cmd += ["--note", note]
        return cmd + metric_args, None

    if action == "snapshot_create":
        cmd = ["vmn", "snapshot", "create", app_name]
        if body.get("note"):
            cmd += ["--note", body["note"]]
        return cmd, None

    if action == "note":
        verstr, note = body.get("verstr"), body.get("note")
        if not verstr or note is None:
            return None, "verstr and note are required"
        return [
            "vmn",
            "experiment",
            "add",
            app_name,
            "-v",
            verstr,
            "--note",
            note,
        ], None

    return None, f"Unknown action '{action}'"


class Job:
    def __init__(self, job_id, command, cwd):
        self.id = job_id
        self.command = command
        self.cwd = cwd
        self.status = "running"
        self.exit_code = None
        self.log = ""
        self.noop = False

    def to_dict(self):
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "log": self.log,
            "noop": self.noop,
        }


class JobRunner:
    """In-memory job table with one concurrent mutation per workspace.

    Bounded on every axis a long-lived server cares about: a job's runtime
    (``timeout_sec``), the number of jobs remembered (``max_jobs``, oldest
    finished first) and the size of each job's captured log.
    """

    def __init__(self, timeout_sec=DEFAULT_JOB_TIMEOUT_SEC, max_jobs=MAX_JOBS):
        self._jobs = OrderedDict()
        self._lock = threading.Lock()
        self._active_workspaces = set()
        self._timeout_sec = timeout_sec
        self._max_jobs = max_jobs

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def _evict_finished(self):
        """Forget the oldest finished jobs beyond the cap; running ones stay."""
        excess = len(self._jobs) - self._max_jobs
        for job_id in [j.id for j in self._jobs.values() if j.status != "running"]:
            if excess <= 0:
                break
            del self._jobs[job_id]
            excess -= 1

    def submit(self, workspace_name, cwd, command):
        """Start a job. Returns (job_dict, error_message_or_None)."""
        with self._lock:
            if workspace_name in self._active_workspaces:
                return None, "Another action is already running in this workspace"
            job = Job(uuid.uuid4().hex, command, cwd)
            self._jobs[job.id] = job
            self._evict_finished()
            self._active_workspaces.add(workspace_name)

        thread = threading.Thread(
            target=self._run, args=(workspace_name, job), daemon=True
        )
        thread.start()
        return job.to_dict(), None

    def _run(self, workspace_name, job):
        # Prefer the real `vmn` console script (faithful to the CLI equivalent
        # shown to the user); fall back to the current interpreter otherwise.
        if shutil.which(job.command[0]):
            argv = job.command
        else:
            argv = [sys.executable, "-m", "version_stamp.cli"] + job.command[1:]
        try:
            proc = subprocess.run(
                argv,
                cwd=job.cwd,
                capture_output=True,
                text=True,
                # The server's stdin is not the job's: a prompt must fail, not hang.
                stdin=subprocess.DEVNULL,
                timeout=self._timeout_sec,
            )
            job.log = _tail((proc.stdout or "") + (proc.stderr or ""))
            job.exit_code = proc.returncode
            job.status = "succeeded" if proc.returncode == 0 else "failed"
            if job.status == "succeeded":
                job.noop = any(m in job.log for m in _NOOP_LOG_MARKERS)
        except subprocess.TimeoutExpired as e:
            output = _as_text(e.stdout) + _as_text(e.stderr)
            job.log = _tail(output + f"\nJob timed out after {self._timeout_sec}s")
            job.exit_code = -1
            job.status = "failed"
        except Exception as e:  # pragma: no cover - defensive
            job.log = str(e)
            job.exit_code = -1
            job.status = "failed"
        finally:
            with self._lock:
                self._active_workspaces.discard(workspace_name)
