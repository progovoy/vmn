#!/usr/bin/env python3
"""``vmn-exp run``: create an experiment, supervise a command, record the outcome.

The run always ends with a final run state, whatever ended it: the child
exiting, a signal to the supervisor (forwarded to the child first), or a
supervision step failing. Only a SIGKILL of the supervisor itself leaves a run
claiming ``running`` — and the stale heartbeat then reports it ``stuck``.
"""

import os
import socket
import subprocess
import tempfile
import threading
import time

from vmn_exp.cli import fork
from vmn_exp.cli.intent_arg import append_intent, read_intent
from vmn_exp.cli.output_tee import OutputTee, output_artifact, popen_kwargs
from vmn_exp.cli.supervise_loop import popen_waiter, watch
from vmn_exp.cli.supervised_env import adopt_requested, supervised_env
from vmn_exp.cli.supervisor import (
    BackgroundSync,
    MetricsTailer,
    SignalForwarder,
    shell_exit_code,
    signal_name,
    supervision_guard,
)
from vmn_exp.cli.supervisor_state import (
    SIGNAL_CHILD_GRACE_SEC,
    StateUploads,
    final_upload_deadline,
    finish_by,
    finish_uploads,
    not_uploaded_warning,
)
from vmn_exp.core.alerts import Alerter, alert_if_failed, load_alert_config
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.metric_compact import compact_by
from vmn_exp.core.rerun import RUNNER_CLI, repo_relative_cwd
from vmn_exp.core.run_error import error_from_output
from vmn_exp.core.run_intervals import resolve_heartbeat_sec, resolve_sync_sec
from vmn_exp.core.state_cas import new_attempt_id
from vmn_exp.core.status import STOPPED
from vmn_exp.core.values import sanitize_entry
from vmn_exp.core.writer import (
    append_entries_to_log,
    append_to_log,
    create_log_entry,
    own_stream,
    sync_to_remote,
)
from version_stamp.api import VMN_LOGGER, measure_runtime_decorator, now_iso

_METRICS_TAIL_INTERVAL = 0.5  # seconds between supervision ticks while the child lives

KILL_GRACE_ENV = "VMN_EXP_KILL_GRACE_SEC"
DEFAULT_KILL_GRACE_SEC = 30
_FINAL_SYNC_TIMEOUT_SEC = 60
_FINAL_STATE_ATTEMPTS = 3

# The end of output.log an error's output_tail is cut from (it keeps far less).
_ERROR_OUTPUT_BYTES = 64 * 1024


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
    """Record the parsed (step, values) records as one block of this writer's
    metric stream (plan 12 §4.1) — append-only, never a rewrite."""
    entries = []
    for step, values in records:
        entry = sanitize_entry(create_log_entry("metrics", values=values))
        if entry is not None:
            if step is not None:
                entry["step"] = step
            entries.append(entry)
    if entries:
        append_entries_to_log(storage, app_name, verstr, entries)


def _safe_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _child_cwd():
    """Where the user invoked vmn: ``$VMN_WORKING_DIR`` when set, else the cwd.

    Not the repo root: ``cd src && vmn-exp run app -- python train.py`` must
    find ``src/train.py``.
    """
    return os.environ.get("VMN_WORKING_DIR") or os.getcwd()


def _kill_graces(args, env):
    """Seconds a child gets to exit before it is killed: ``(after a stop the
    supervisor requests, after a signal it received)``. An explicit
    ``--kill-grace-sec`` or *env*'s ``VMN_EXP_KILL_GRACE_SEC`` sets both;
    by default a signal leaves the child less, so that it and the final
    uploads fit the signal budget."""
    value = getattr(args, "kill_grace_sec", None)
    if value is None:
        value = env.get(KILL_GRACE_ENV)
    try:
        if value is not None:
            grace = max(0.0, float(value))
            return grace, grace
    except ValueError:
        VMN_LOGGER.warning(f"Ignoring invalid {KILL_GRACE_ENV}={value!r}")
    return DEFAULT_KILL_GRACE_SEC, SIGNAL_CHILD_GRACE_SEC


def _detect_python_exe(run_cmd):
    """Return a Python executable to probe if *run_cmd* is a Python process.

    Covers two cases:
    * ``python[3][.x]`` or ``pythonX.Y`` as the interpreter (argv[0]).
    * A ``.py`` script run directly — use ``sys.executable`` as best proxy.
    """
    import sys

    if not run_cmd:
        return None
    exe = run_cmd[0]
    import re

    basename = os.path.basename(exe)
    if re.match(r"^python[\d.]*$", basename):
        return exe  # e.g. python, python3, python3.10
    if exe.endswith(".py"):
        return sys.executable  # script invoked directly; use our interpreter
    return None


def _create_experiment(vcs, storage, args, extra_create_data=None):
    """Create the run's experiment record. Returns ``(app_name, verstr, err)``.

    *extra_create_data* (params, tags, ...) wins over what ``--file`` holds.
    """
    import vmn_exp.cli.experiment as cli

    from_snapshot = getattr(args, "from_snapshot", None) or os.environ.get(
        "VMN_SNAPSHOT_METADATA"
    )
    extra = {}
    if getattr(args, "file", None):
        notes_data = cli._parse_notes_file(args.file)
        for key in ("params", "hypothesis", "tags"):
            if key in notes_data:
                extra[key] = notes_data[key]
    extra.update(extra_create_data or {})

    app_name = cli._app_name(vcs, args)
    parent, err = cli._resolve_parent(storage, app_name, args)
    if err is not None:
        return app_name, None, err
    source, err = fork.fork_source(storage, app_name, args)
    if err is not None:
        return app_name, None, err

    run_cmd = getattr(args, "run_cmd", None)
    python_exe = _detect_python_exe(run_cmd) if run_cmd else None
    capture_env = getattr(args, "capture_env", None)

    verstr, err = cli._experiment_create_core(
        vcs,
        storage,
        note=args.note,
        from_snapshot=from_snapshot,
        extra_create_data=extra or None,
        parent=parent,
        name=getattr(args, "run_name", None),
        capture_env=capture_env,
        python_exe=python_exe,
    )
    if err is None:
        fork.seed(storage, app_name, verstr, source)
    return app_name, verstr, err


@measure_runtime_decorator
def experiment_run(vcs, params, storage, args, repo_lock=None, *, io):
    """Create an experiment, run a command, and record its outcome + metrics.

    The child's stdout/stderr stream live and are kept as the ``output.log``
    artifact (see ``output_tee``; not with ``--no-capture-output``, where it
    inherits stdio). It gets these env vars:
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
            "No command to run. Usage: vmn-exp run <app> -- <command> [args...]"
        )
        return 2
    intent, err = read_intent(args)
    if err is not None:
        return err

    app_name, verstr, err = _create_experiment(vcs, storage, args)
    if err is not None:
        return err
    if intent:
        append_intent(storage, app_name, verstr, intent)

    import vmn_exp.cli.experiment as cli
    cli._append_inputs(storage, app_name, verstr, getattr(args, "inputs", None))

    # The mutating phase is over: everything below writes only inside this run's
    # own experiment directory. Hand the repo back to other vmn commands - the
    # child's included.
    if repo_lock is not None:
        repo_lock.release()

    from vmn_exp.cli.similar_hint import print_hint

    exp_conf = experiment_conf(vcs)
    print_hint(storage, app_name, verstr, args, exp_conf, command=run_cmd)
    return run_supervision(
        storage, app_name, verstr, args, exp_conf,
        getattr(vcs, "vmn_root_path", None), os.environ,
    ).run(run_cmd)


def run_supervision(storage, app_name, verstr, args, exp_conf, root, env):
    """The supervision of ``vmn-exp run``: it offers the run to its child
    unless ``--no-adopt`` or ``VMN_EXP_ADOPT`` in *env* turn that off."""
    return _Supervision(storage, app_name, verstr, args, exp_conf, root=root,
                        adopt=adopt_requested(args, env), wait=threading.Event().wait)


class _Supervision:
    """One supervised child: start it, watch it, and record how it ended.

    The child runs in *cwd* (default: where vmn was invoked); ``run_state.yml``
    records that cwd relative to *root* (the repo root; None records null).
    *extra_env* is applied last; a None value removes the variable.
    *state_extra* adds fields to ``run_state.yml``.
    *adopt* offers the run to the direct child (``supervised_env``).
    *wait(delay)* is the pause between retries of the final uploads
    (``threading.Event().wait``); it reports whether they were abandoned.
    """

    def __init__(self, storage, app_name, verstr, args, exp_conf=None,
                 extra_env=None, on_tick=None, cwd=None, root=None, state_extra=None,
                 *, adopt=False, wait):
        self.storage = storage
        self.adopt = adopt
        self.state_extra = state_extra or {}
        self.cwd = cwd or _child_cwd()
        self.root = root
        self.extra_env = extra_env or {}
        # Called with this supervision on every poll while the child lives.
        self.on_tick = on_tick
        self.stopped_early = False
        self.exp_conf = exp_conf
        self.app_name = app_name
        self.verstr = verstr
        self.args = args
        self.guard = supervision_guard()
        self.wait = wait
        self.sync = BackgroundSync(self._sync_once, self._sync_final, wait)
        self.state_uploads = StateUploads(storage, app_name, verstr, wait, self.guard)
        self.forwarder = SignalForwarder(*_kill_graces(args, os.environ))
        self.output = output_artifact(storage, app_name, verstr, args)
        self.tee = None
        # Every stream the metrics were appended to: an adopted child that
        # compacts its own stream moves the copy on to a new owner's.
        self.appended_streams = set()

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
        from vmn_exp.sdk import sysmetrics  # exp's __init__ imports the CLI

        self.samples_tree = sysmetrics.enabled(
            getattr(self.args, "system_metrics", None), self.exp_conf
        )
        env = self._child_env(dict(os.environ), os.getpid())
        try:
            stdio = popen_kwargs(env) if self.output else {"env": env}
            proc = subprocess.Popen(run_cmd, cwd=self.cwd, **stdio)
        except FileNotFoundError:
            VMN_LOGGER.error("Command not found: " + run_cmd[0])
            return None
        except OSError as exc:
            VMN_LOGGER.error(f"Could not start {run_cmd[0]}: {exc}")
            return None
        self.forwarder.attach(proc)
        if self.output:
            self.tee = OutputTee(proc, self.output.write)
        return proc

    def _child_env(self, base_env, pid):
        return supervised_env(
            base_env, self.verstr, self.app_name, self.metrics_path,
            self.samples_tree, self.extra_env, pid if self.adopt else None,
        )

    def _supervise(self, proc, run_cmd):
        heartbeat_interval = resolve_heartbeat_sec(
            getattr(self.args, "heartbeat_interval", None), self.exp_conf
        )
        started_at = now_iso()
        self.run_state = {
            "state": "running",
            "command": list(run_cmd),
            "runner": RUNNER_CLI,
            "cwd": repo_relative_cwd(self.cwd, self.root),
            "pid": proc.pid,
            "host": socket.gethostname(),
            # One schema with the SDK's: this process's attempt at the run.
            "attempt": new_attempt_id(),
            "started_at": started_at,
            "heartbeat": started_at,
            # Bumped every beat: a liveness signal that needs no clock.
            "heartbeat_seq": 0,
            "heartbeat_interval_sec": heartbeat_interval,
            "exit_code": None,
            "finished_at": None,
            "duration_sec": None,
            **self.state_extra,
        }
        self._publish("run state")
        self._defer_ships()

        from vmn_exp.sdk import sysmetrics  # exp's __init__ imports the CLI

        # The child is the workload, so it is the child's tree that gets measured.
        sampler = sysmetrics.Sampler(
            lambda values: self._ingest([(None, values)]),
            self.samples_tree,
            pid=proc.pid,
        )

        sync_interval = resolve_sync_sec(
            getattr(self.args, "sync_interval", None), self.exp_conf
        )
        tick = self._tick(sampler, sync_interval, heartbeat_interval, time.monotonic())
        watch(lambda: proc.poll() is not None, popen_waiter(proc), tick,
              time.monotonic, _METRICS_TAIL_INTERVAL)

    def _tick(self, sampler, sync_interval, heartbeat_interval, started):
        """One poll while the child lives: ingest, sync, beat, hook, grace."""
        last_sync = last_heartbeat = started

        def tick(now):
            nonlocal last_sync, last_heartbeat
            self.guard("metrics ingestion", self._ingest_new)
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
            if self.on_tick is not None:
                self.guard("supervision hook", self.on_tick, self)
            self.forwarder.enforce_grace()

        return tick

    def request_stop(self):
        """End the child early, on purpose: SIGTERM now, SIGKILL after the grace.

        The run state records ``end_reason: stopped``, which status derivation
        reads as a success whatever code the child exits with.
        """
        self.stopped_early = True
        self.forwarder.request_stop()

    def _stop(self, proc):
        """Make sure the child is gone: supervision never leaves an orphan."""
        if proc.poll() is not None:
            return
        self.forwarder.enforce_grace()
        try:
            proc.terminate()
            proc.wait(timeout=self.forwarder.grace_sec)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
        proc.wait()

    def _finish(self, proc, run_cmd):
        """Record how the run ended; every step is best-effort but attempted."""
        returncode = proc.returncode
        exit_code = shell_exit_code(returncode)
        duration = round(time.monotonic() - self.start, 3)
        self.guard("metrics ingestion", self._ingest_new)
        self._record_output()

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
        if self.stopped_early:
            final["end_reason"] = STOPPED
        elif exit_code != 0:
            error = self.guard("output error", self._output_error)
            if error:
                final["error"] = error
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
        # A request after this would be a periodic sync replacing the final one.
        self._undefer_ships()
        deadline = self._finish_uploads()
        signalled = self.forwarder.signalled_at is not None
        if not signalled:
            deadline = time.monotonic() + _FINAL_SYNC_TIMEOUT_SEC
        for stream in sorted(self.appended_streams | {self._own_stream()}):
            self.guard("metric compaction", compact_by, self.storage, self.app_name,
                       self.verstr, stream, deadline)
        self._alert(deadline if signalled else None)
        VMN_LOGGER.info(f"Experiment {self.verstr}: exited {exit_code} in {duration}s")
        return exit_code

    def _record_output(self):
        """Drain the child's output; the final sync uploads it."""
        if self.output is None:
            return
        if self.tee is not None:
            self.tee.drain()
        self.guard(
            "output log entry",
            lambda: append_to_log(
                self.storage, self.app_name, self.verstr, self.output.seal()
            ),
        )

    def _output_error(self):
        """The ``error`` parsed from the captured output; None without capture."""
        if not self.output:
            return None
        stderr = self.tee.stderr_text() if self.tee else None
        return error_from_output(
            self.output.tail_text(_ERROR_OUTPUT_BYTES), traceback_text=stderr
        )

    def _publish(self, what, **updates):
        self.run_state.update(updates)
        self.guard(what, self.state_uploads.publish, self.run_state)

    def _publish_final(self, final):
        """The final state is what separates ``failed`` from ``stuck``: retry it."""
        if not hasattr(self, "run_state"):
            return  # the child never got as far as a published run
        self.run_state.update(final)
        for attempt in range(_FINAL_STATE_ATTEMPTS):
            try:
                self.state_uploads.publish(self.run_state, final=True)
                return
            except Exception:
                VMN_LOGGER.debug("Final run state write failed", exc_info=True)
                if attempt + 1 < _FINAL_STATE_ATTEMPTS:
                    self.wait(1)
        VMN_LOGGER.warning(
            f"Experiment {self.verstr}: could not record the final run state"
        )

    def _finish_uploads(self):
        """The final log sync, then the final state's upload, in one budget
        that starts now, with the final state submitted; the deadline."""
        clock = time.monotonic
        deadline = final_upload_deadline(
            clock(), _FINAL_SYNC_TIMEOUT_SEC,
            self.forwarder.signalled_at, self.forwarder.signal_grace_sec,
        )
        if not finish_uploads(self.sync, self.state_uploads, deadline, clock):
            VMN_LOGGER.warning(not_uploaded_warning(
                self.verstr, self.state_uploads.last_error, self.storage))
        return deadline

    def _defer_ships(self):
        """Due ships of a direct-to-bucket log buffer become requests to the
        sync worker, never uploads on the supervise loop."""
        defer = getattr(self.storage, "defer_ships", None)
        if defer is not None:
            defer(self.app_name, self.verstr, self.sync.request)

    def _undefer_ships(self):
        undefer = getattr(self.storage, "undefer_ships", None)
        if undefer is not None:
            undefer(self.app_name, self.verstr)

    def _alert(self, deadline):
        """The failure alert; after a signal, only until *deadline*."""
        def alert():
            self.guard("failure alert", self._alert_if_failed)

        if deadline is None:
            alert()
        elif not finish_by(deadline, time.monotonic, alert):
            VMN_LOGGER.warning(
                f"Experiment {self.verstr}: the failure alert did not finish in time")

    def _alert_if_failed(self):
        alerter = Alerter(load_alert_config(self.app_name, self.exp_conf))
        alert_if_failed(
            self.storage, self.app_name, self.verstr,
            getattr(self, "run_state", None), alerter,
            run_name=getattr(self.args, "run_name", None),
        )

    def _ingest_new(self):
        self._ingest(self.tailer.poll())

    def _ingest(self, records):
        if records:
            self.appended_streams.add(self._own_stream())
        _ingest_metric_records(self.storage, self.app_name, self.verstr, records)

    def _own_stream(self):
        return own_stream(self.storage, self.app_name, self.verstr)

    def _sync_once(self):
        # The log first: a slow output PUT must not hold back liveness data.
        self.guard(
            "remote sync",
            sync_to_remote,
            self.storage,
            self.app_name,
            self.verstr,
        )
        if self.output is not None:
            self.guard("output log upload", self.output.upload)

    def _sync_final(self):
        """The last sync, unguarded: a failure reaches the final retry. Both
        steps resume from what the remote holds, so a retry repeats nothing."""
        sync_to_remote(self.storage, self.app_name, self.verstr)
        if self.output is not None:
            self.output.upload()
