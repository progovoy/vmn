#!/usr/bin/env python3
"""``vmn exp run``: create an experiment, supervise a command, record the outcome.

The run always ends with a final run state, whatever ended it: the child
exiting, a signal to the supervisor (forwarded to the child first), or a
supervision step failing. Only a SIGKILL of the supervisor itself leaves a run
claiming ``running`` — and the stale heartbeat then reports it ``stuck``.
"""

import os
import socket
import subprocess
import tempfile
import time

from version_stamp.cli.experiment_supervisor import (
    BackgroundSync,
    MetricsTailer,
    SignalForwarder,
    shell_exit_code,
    signal_name,
    supervision_guard,
)
from version_stamp.core.experiment_status import DEFAULT_HEARTBEAT_INTERVAL_SEC
from version_stamp.core.experiment_writer import (
    append_to_log,
    create_log_entry,
    get_writer_id,
    save_run_state,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import now_iso

_METRICS_TAIL_INTERVAL = 0.5  # seconds between metrics-file polls during a run

KILL_GRACE_ENV = "VMN_EXP_KILL_GRACE_SEC"
DEFAULT_KILL_GRACE_SEC = 30
_FINAL_SYNC_TIMEOUT_SEC = 60
_FINAL_STATE_ATTEMPTS = 3


def _parse_metrics(metrics_list):
    """Parse ['loss=0.34', 'acc=0.91'] to {'loss': 0.34, 'acc': 0.91}."""
    result = {}
    for item in metrics_list:
        if "=" not in item:
            VMN_LOGGER.error(f"Invalid --metrics format: {item}. Expected key=value")
            continue
        key, val = item.split("=", 1)
        try:
            result[key.strip()] = float(val.strip())
        except ValueError:
            result[key.strip()] = val.strip()
    return result


def _parse_metric_line(line):
    """Parse one metrics-file line into ``(step_or_None, values)``.

    Grammar: ``[step=N] key=value [key=value ...]``. Returns None for lines
    with no metric values.
    """
    tokens = line.split()
    step = None
    if tokens and tokens[0].startswith("step="):
        try:
            step = int(tokens[0][len("step=") :])
            tokens = tokens[1:]
        except ValueError:
            pass  # "step" used as a metric name; leave tokens intact
    values = _parse_metrics(tokens)
    if not values:
        return None
    return step, values


class _MetricsTailer(MetricsTailer):
    """The metrics-file tailer, parsing ``[step=N] key=value ...`` lines."""

    def __init__(self, path):
        super().__init__(path, _parse_metric_line)


def _ingest_metric_records(storage, app_name, verstr, records):
    """Append one metrics log entry per parsed (step, values) record.

    Strictly append-only, into this writer's own JSONL file. Reading the merged
    log and rewriting ``log.yml`` instead would copy every entry already held in
    a per-writer file into the shared one — duplicating them once per flush —
    and would clobber anything another writer appended meanwhile.
    """
    for step, values in records:
        entry = create_log_entry("metrics", values=values)
        if step is not None:
            entry["step"] = step
        append_to_log(storage, app_name, verstr, entry)


def _safe_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _child_cwd():
    """Where the user invoked vmn: ``$VMN_WORKING_DIR`` when set, else the cwd.

    Not the repo root: ``cd src && vmn exp run app -- python train.py`` must
    find ``src/train.py``.
    """
    return os.environ.get("VMN_WORKING_DIR") or os.getcwd()


def _kill_grace_sec(args):
    """Seconds a signalled child gets to exit before it is killed."""
    value = getattr(args, "kill_grace_sec", None)
    if value is None:
        value = os.environ.get(KILL_GRACE_ENV)
    try:
        return max(0.0, float(value)) if value is not None else DEFAULT_KILL_GRACE_SEC
    except ValueError:
        VMN_LOGGER.warning(f"Ignoring invalid {KILL_GRACE_ENV}={value!r}")
        return DEFAULT_KILL_GRACE_SEC


def _create_experiment(vcs, storage, args):
    """Create the run's experiment record. Returns ``(app_name, verstr, err)``."""
    from version_stamp.cli import experiment as cli

    from_snapshot = getattr(args, "from_snapshot", None) or os.environ.get(
        "VMN_SNAPSHOT_METADATA"
    )
    extra = {}
    if getattr(args, "file", None):
        notes_data = cli._parse_notes_file(args.file)
        for key in ("params", "hypothesis", "tags"):
            if key in notes_data:
                extra[key] = notes_data[key]

    app_name = cli._app_name(vcs, args)
    parent, err = cli._resolve_parent(storage, app_name, args)
    if err is not None:
        return app_name, None, err

    verstr, err = cli._experiment_create_core(
        vcs,
        storage,
        note=args.note,
        from_snapshot=from_snapshot,
        extra_create_data=extra or None,
        parent=parent,
        name=getattr(args, "run_name", None),
    )
    return app_name, verstr, err


@measure_runtime_decorator
def experiment_run(vcs, params, storage, args, repo_lock=None):
    """Create an experiment, run a command, and record its outcome + metrics.

    The child inherits stdio (output streams live) and these env vars:
    VMN_EXPERIMENT_ID, VMN_APP_NAME, VMN_METRICS_FILE. Any ``key=value`` lines the
    child appends to VMN_METRICS_FILE are recorded as a metrics entry. Returns the
    child's exit code, ``128 + N`` when signal N ended it.

    ``repo_lock`` is the per-repo lock the CLI entry point acquired. Creating the
    experiment may auto-initialize the repo and stamp a baseline, so it runs under
    the lock; supervising the child must not, or a run that trains for hours locks
    the repo for hours and a nested ``vmn`` deadlocks.
    """
    run_cmd = getattr(args, "run_cmd", None)
    if not run_cmd:
        VMN_LOGGER.error(
            "No command to run. Usage: vmn exp run <app> -- <command> [args...]"
        )
        return 1

    app_name, verstr, err = _create_experiment(vcs, storage, args)
    if err is not None:
        return err

    # The mutating phase is over: everything below writes only inside this run's
    # own experiment directory. Hand the repo back to other vmn commands - the
    # child's included.
    if repo_lock is not None:
        repo_lock.release()

    return _Supervision(storage, app_name, verstr, args).run(run_cmd)


class _Supervision:
    """One supervised child: start it, watch it, and record how it ended."""

    def __init__(self, storage, app_name, verstr, args):
        self.storage = storage
        self.app_name = app_name
        self.verstr = verstr
        self.args = args
        self.guard = supervision_guard()
        self.sync = BackgroundSync(self._sync_once)
        self.forwarder = SignalForwarder(_kill_grace_sec(args))
        self.writer_id = get_writer_id()

    def run(self, run_cmd):
        fd, self.metrics_path = tempfile.mkstemp(prefix="vmn-metrics-")
        os.close(fd)
        self.tailer = _MetricsTailer(self.metrics_path)

        VMN_LOGGER.info(f"Experiment {self.verstr}: running {' '.join(run_cmd)}")
        self.forwarder.install()
        try:
            proc = self._start(run_cmd)
            if proc is None:
                return 1
            self.start = time.monotonic()
            try:
                self._supervise(proc, run_cmd)
            finally:
                self._stop(proc)
                exit_code = self._finish(proc, run_cmd)
        finally:
            self.forwarder.restore()
            _safe_unlink(self.metrics_path)
        print(self.verstr)
        return exit_code

    def _start(self, run_cmd):
        env = dict(os.environ)
        env["VMN_EXPERIMENT_ID"] = self.verstr
        env["VMN_APP_NAME"] = self.app_name or ""
        env["VMN_METRICS_FILE"] = self.metrics_path
        try:
            proc = subprocess.Popen(run_cmd, env=env, cwd=_child_cwd())
        except FileNotFoundError:
            VMN_LOGGER.error("Command not found: " + run_cmd[0])
            return None
        except OSError as exc:
            VMN_LOGGER.error(f"Could not start {run_cmd[0]}: {exc}")
            return None
        self.forwarder.attach(proc)
        return proc

    def _supervise(self, proc, run_cmd):
        heartbeat_interval = (
            getattr(self.args, "heartbeat_interval", None)
            or DEFAULT_HEARTBEAT_INTERVAL_SEC
        )
        started_at = now_iso()
        self.run_state = {
            "state": "running",
            "command": list(run_cmd),
            "pid": proc.pid,
            "host": socket.gethostname(),
            "started_at": started_at,
            "heartbeat": started_at,
            # Bumped every beat: a liveness signal that needs no clock.
            "heartbeat_seq": 0,
            "heartbeat_interval_sec": heartbeat_interval,
            "exit_code": None,
            "finished_at": None,
            "duration_sec": None,
        }
        self._publish("run state")

        from version_stamp.exp import sysmetrics  # exp's __init__ imports the CLI

        # The child is the workload, so it is the child's tree that gets measured.
        sampler = sysmetrics.Sampler(
            lambda values: self._ingest([(None, values)]),
            getattr(self.args, "system_metrics", False),
            pid=proc.pid,
        )

        sync_interval = getattr(self.args, "sync_interval", 30)
        last_sync = last_heartbeat = time.monotonic()
        while proc.poll() is None:
            self.guard("metrics ingestion", self._ingest_new)
            now = time.monotonic()
            if sync_interval and now - last_sync > sync_interval:
                self.sync.request()
                last_sync = now
            if now - last_heartbeat >= heartbeat_interval:
                self._publish(
                    "heartbeat",
                    heartbeat=now_iso(),
                    heartbeat_seq=self.run_state["heartbeat_seq"] + 1,
                )
                self.guard("system metrics", sampler.tick)
                last_heartbeat = now
            self.forwarder.enforce_grace()
            time.sleep(_METRICS_TAIL_INTERVAL)

    def _stop(self, proc):
        """Make sure the child is gone: supervision never leaves an orphan."""
        if proc.poll() is not None:
            return
        self.forwarder.enforce_grace()
        try:
            proc.terminate()
            proc.wait(timeout=_kill_grace_sec(self.args))
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
        proc.wait()

    def _finish(self, proc, run_cmd):
        """Record how the run ended; every step is best-effort but attempted."""
        returncode = proc.returncode
        exit_code = shell_exit_code(returncode)
        duration = round(time.monotonic() - self.start, 3)
        self.guard("metrics ingestion", self._ingest_new)

        final = {
            "state": "finished",
            "exit_code": exit_code,
            "finished_at": now_iso(),
            "duration_sec": duration,
        }
        if returncode < 0:
            final["signal"] = signal_name(-returncode)
        if self.forwarder.received:
            final["received_signal"] = self.forwarder.received
        self._publish_final(final)

        self.guard(
            "run log entry",
            append_to_log,
            self.storage,
            self.app_name,
            self.verstr,
            create_log_entry(
                "run", command=run_cmd, exit_code=exit_code, duration_sec=duration
            ),
        )
        self.sync.final(_FINAL_SYNC_TIMEOUT_SEC)
        VMN_LOGGER.info(f"Experiment {self.verstr}: exited {exit_code} in {duration}s")
        return exit_code

    def _publish(self, what, **updates):
        self.guard(
            what,
            save_run_state,
            self.storage,
            self.app_name,
            self.verstr,
            self.run_state,
            **updates,
        )

    def _publish_final(self, final):
        """The final state is what separates ``failed`` from ``stuck``: retry it."""
        if not hasattr(self, "run_state"):
            return  # the child never got as far as a published run
        for attempt in range(_FINAL_STATE_ATTEMPTS):
            try:
                save_run_state(
                    self.storage, self.app_name, self.verstr, self.run_state, **final
                )
                return
            except Exception:
                VMN_LOGGER.debug("Final run state write failed", exc_info=True)
                if attempt + 1 < _FINAL_STATE_ATTEMPTS:
                    time.sleep(1)
        VMN_LOGGER.warning(
            f"Experiment {self.verstr}: could not record the final run state"
        )

    def _ingest_new(self):
        self._ingest(self.tailer.poll())

    def _ingest(self, records):
        _ingest_metric_records(self.storage, self.app_name, self.verstr, records)

    def _sync_once(self):
        self.guard(
            "remote sync",
            self.storage.sync_log_to_remote,
            self.app_name,
            self.verstr,
            self.writer_id,
        )
