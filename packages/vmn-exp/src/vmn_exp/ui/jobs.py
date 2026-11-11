#!/usr/bin/env python3
"""Mutation job runner for vmn-exp ui.

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

from vmn_exp.ui.job_argv import ACTIONS, opt, positional, switch
from vmn_exp.ui.jobs_exp_meta import (  # noqa: F401  (_metric_args: tests)
    MAX_ARCHIVE_BATCH,
    _metric_args,
    _valid_verstr,
    exp_add_command,
    exp_archive_command,
    exp_create_command,
    exp_note_command,
    exp_prune_command,
    exp_push_command,
    exp_restore_command,
    exp_rewind_command,
    exp_tag_command,
)

# A job that waits on a credential prompt or a lock must not pin its workspace
# forever: it fails after this long and frees the slot.
DEFAULT_JOB_TIMEOUT_SEC = 30 * 60
# The job table lives in memory for the server's lifetime; keep it bounded.
MAX_JOBS = 200
MAX_JOB_LOG_BYTES = 1_000_000
_TRUNCATED_MARKER = "[... earlier output truncated ...]\n"

# Console script -> module, for when the script is not on PATH.
_CLI_MODULES = {"vmn": "version_stamp.cli", "vmn-exp": "vmn_exp.cli"}


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


_RELEASE_MODES = ("major", "minor", "patch", "hotfix")


def _version_args(body):
    """``--version=<verstr>``, or nothing for a missing or empty verstr."""
    verstr = body.get("verstr")
    if verstr is None or verstr == "":
        return [], None
    if not _valid_verstr(verstr):
        return None, "A valid verstr is required"
    return [opt("--version", verstr)], None


def _stamp_command(app_name, body):
    mode, prerelease = body.get("release_mode"), body.get("prerelease")
    if mode not in _RELEASE_MODES:
        return None, "release_mode must be major|minor|patch|hotfix"
    cmd = ["vmn", "stamp", opt("--release-mode", mode)]
    if prerelease:
        if not isinstance(prerelease, str) or not prerelease.isprintable():
            return None, "prerelease must be a printable string"
        cmd.append(opt("--pr", prerelease))
    if body.get("dry_run"):
        cmd.append(switch("--dry-run"))
    return cmd + [positional(app_name)], None


def _core_version_command(verb):
    """``vmn release|goto [--version=<verstr>] <app>``."""
    def build(app_name, body):
        args, err = _version_args(body)
        if err:
            return None, err
        return ["vmn", verb, *args, positional(app_name)], None

    return build


def _exp_archive(verb):
    return lambda app_name, body: exp_archive_command(verb, app_name, body)


_BUILDERS = {
    "stamp": _stamp_command,
    "release": _core_version_command("release"),
    "goto": _core_version_command("goto"),
    "restore": exp_restore_command,
    "prune": exp_prune_command,
    "exp_create": exp_create_command,
    "exp_add": exp_add_command,
    "note": exp_note_command,
    "exp_tag": exp_tag_command,
    "exp_rewind": exp_rewind_command,
    "exp_push": exp_push_command,
    "exp_archive": _exp_archive("archive"),
    "exp_unarchive": _exp_archive("unarchive"),
}


def build_command(action, app_name, body):
    """Translate an action + request body into a ``vmn``/``vmn-exp`` argv list.

    Returns (argv, error_message_or_None). Kept pure for testing/preview.
    """
    if action not in ACTIONS:
        return None, f"Unknown action '{action}'"
    try:
        return _BUILDERS[action](app_name, body or {})
    except ValueError as e:
        return None, str(e)


class Job:
    def __init__(self, job_id, command, cwd):
        self.id = job_id
        self.command = command
        self.cwd = cwd
        self.status = "running"
        self.exit_code = None
        self.log = ""
        self.progress = None

    def to_dict(self):
        job = {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "log": self.log,
        }
        if self.progress is not None:
            job["progress"] = dict(self.progress)
        return job


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
        return self._start(workspace_name, Job(uuid.uuid4().hex, command, cwd), self._run)

    def submit_call(self, workspace_name, command, call):
        """Start an in-process job: *call()* returns its log text; raising
        fails the job with the exception's message as its log."""
        job = Job(uuid.uuid4().hex, command, None)
        return self._start(workspace_name, job, lambda ws, j: self._call(ws, j, call))

    def submit_bulk(self, workspace_name, command, resolve, act):
        """Start a bulk job (plan 23 S4): *resolve()* names its runs when it
        starts, *act(batch)* acts on each :data:`MAX_ARCHIVE_BATCH` of them
        (returning log text, raising to fail); ``progress`` counts them."""
        job = Job(uuid.uuid4().hex, command, None)
        job.progress = {"done": 0, "total": None}

        def call():
            verstrs = resolve()
            job.progress["total"] = len(verstrs)
            logs = []
            for at in range(0, len(verstrs), MAX_ARCHIVE_BATCH):
                batch = verstrs[at : at + MAX_ARCHIVE_BATCH]
                logs.append(str(act(batch) or ""))
                job.progress["done"] += len(batch)
            return "\n".join(logs)

        return self._start(workspace_name, job, lambda ws, j: self._call(ws, j, call))

    def run_command(self, command, cwd):
        """Run *command* as a job does; ``(exit_code, output)``, raising
        :class:`subprocess.TimeoutExpired` past the job timeout."""
        # Prefer the real console script (faithful to the CLI equivalent
        # shown to the user); fall back to the current interpreter otherwise.
        if shutil.which(command[0]):
            argv = command
        else:
            argv = [sys.executable, "-m", _CLI_MODULES[command[0]]] + command[1:]
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            # The server's stdin is not the job's: a prompt must fail, not hang.
            stdin=subprocess.DEVNULL,
            timeout=self._timeout_sec,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def _start(self, workspace_name, job, target):
        with self._lock:
            if workspace_name in self._active_workspaces:
                return None, "Another action is already running in this workspace"
            self._jobs[job.id] = job
            self._evict_finished()
            self._active_workspaces.add(workspace_name)
            submitted = job.to_dict()

        thread = threading.Thread(target=target, args=(workspace_name, job), daemon=True)
        thread.start()
        return submitted, None

    def _call(self, workspace_name, job, call):
        try:
            job.log = _tail(str(call() or ""))
            job.exit_code, job.status = 0, "succeeded"
        except Exception as e:
            job.log = _tail(str(e))
            job.exit_code, job.status = 1, "failed"
        finally:
            with self._lock:
                self._active_workspaces.discard(workspace_name)

    def _run(self, workspace_name, job):
        try:
            job.exit_code, output = self.run_command(job.command, job.cwd)
            job.log = _tail(output)
            job.status = "succeeded" if job.exit_code == 0 else "failed"
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
