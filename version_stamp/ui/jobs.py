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
            "vmn", "experiment", "add", app_name, "-v", verstr, "--note", note,
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

    def to_dict(self):
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "log": self.log,
        }


class JobRunner:
    """In-memory job table with one concurrent mutation per workspace."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._active_workspaces = set()

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def submit(self, workspace_name, cwd, command):
        """Start a job. Returns (job_dict, error_message_or_None)."""
        with self._lock:
            if workspace_name in self._active_workspaces:
                return None, "Another action is already running in this workspace"
            job = Job(uuid.uuid4().hex, command, cwd)
            self._jobs[job.id] = job
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
                argv, cwd=job.cwd, capture_output=True, text=True,
            )
            job.log = (proc.stdout or "") + (proc.stderr or "")
            job.exit_code = proc.returncode
            job.status = "succeeded" if proc.returncode == 0 else "failed"
        except Exception as e:  # pragma: no cover - defensive
            job.log = str(e)
            job.exit_code = -1
            job.status = "failed"
        finally:
            with self._lock:
                self._active_workspaces.discard(workspace_name)
